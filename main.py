import os
import re
import tempfile
import time
import random
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from supabase import create_client
from openai import OpenAI
import requests
from urllib.parse import quote
from pypdf import PdfReader

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = "tJvgmaVM5tDwPVrtn8TA"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def normalize_text(text: str) -> str:
    return (text or "").replace("\\'", "'").replace("\\", "").strip()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_date(value: str):
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
        return None


def get_memory_importance(memory_type, emotion="neutre"):
    if memory_type in ["name", "identity", "objectif", "projet", "travail", "relation", "emotion"]:
        return "high"

    if memory_type in ["preference", "habitude"]:
        return "medium"

    if memory_type == "conversation":
        return "low"

    return "medium"


def get_recent_memories(user_id: str, limit=12):
    try:
        result = (
            supabase.table("memories")
            .select("messages,created_at,type,importance,role")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        memories = result.data or []
        memories.reverse()
        return memories

    except Exception as e:
        print("MEMORY READ ERROR:", e)
        return []


def save_memory(user_id, role, message, emotion="neutre", memory_type="conversation"):
    try:
        message = normalize_text(message)

        if not message:
            return

        existing = (
            supabase.table("memories")
            .select("*")
            .eq("user_id", user_id)
            .eq("messages", message)
            .eq("type", memory_type)
            .execute()
        )

        if existing.data and len(existing.data) > 0:
            return

        supabase.table("memories").insert({
            "user_id": user_id,
            "messages": message,
            "emotion": emotion,
            "role": role,
            "type": memory_type,
            "importance": get_memory_importance(memory_type, emotion),
        }).execute()

    except Exception as e:
        print("MEMORY SAVE ERROR:", e)


def extract_name(message: str):
    cleaned = normalize_text(message)
    match = re.search(r"je m['’]appelle\s+([A-Za-zÀ-ÿ\-]+)", cleaned, re.IGNORECASE)
    if match:
        return match.group(1).strip().capitalize()
    return None


def extract_fact(message: str):
    cleaned = normalize_text(message)
    lowered = cleaned.lower()

    patterns = [
        (r"mon objectif est de\s+(.+)", "objectif"),
        (r"je veux\s+(.+)", "objectif"),
        (r"je compte\s+(.+)", "projet"),
        (r"je vais\s+(.+)", "projet"),

        (r"je préfère\s+(.+)", "preference"),
        (r"j'aime\s+(.+)", "preference"),
        (r"j’adore\s+(.+)", "preference"),

        (r"je travaille sur\s+(.+)", "travail"),
        (r"mon projet est\s+(.+)", "travail"),

        (r"ma copine\s+(.+)", "relation"),
        (r"mon frère\s+(.+)", "relation"),
        (r"ma soeur\s+(.+)", "relation"),
        (r"mon ami\s+(.+)", "relation"),

        (r"je suis triste\s*(.+)?", "emotion"),
        (r"je suis heureux\s*(.+)?", "emotion"),
        (r"j'ai peur de\s+(.+)", "emotion"),

        (r"je fais du sport\s*(.+)?", "habitude"),
        (r"je vais à la salle\s*(.+)?", "habitude"),
    ]

    for pattern, fact_type in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            value = match.group(1).strip() if match.group(1) else cleaned
            if value:
                return {
                    "fact_type": fact_type,
                    "value": value,
                }

    return None


def get_user_name(user_id: str):
    try:
        result = (
            supabase.table("user_profile")
            .select("name")
            .eq("user_id", user_id)
            .execute()
        )

        if result.data and len(result.data) > 0:
            return result.data[0].get("name")

    except Exception as e:
        print("ERREUR get_user_name:", e)

    return None


def save_user_name(user_id: str, name: str):
    try:
        supabase.table("user_profile").upsert({
            "user_id": user_id,
            "name": name,
            "updated_at": now_utc_iso(),
        }).execute()

        existing_name_fact = (
            supabase.table("memories")
            .select("messages")
            .eq("user_id", user_id)
            .eq("type", "name")
            .eq("messages", name)
            .execute()
        )

        if not existing_name_fact.data:
            save_memory(user_id, "system", name, "neutre", "name")

    except Exception as e:
        print("ERREUR save_user_name:", e)


def get_user_facts(user_id: str) -> dict:
    facts = {}

    try:
        result = (
            supabase.table("memories")
            .select("messages,type")
            .eq("user_id", user_id)
            .in_("type", [
                "name",
                "objectif",
                "preference",
                "projet",
                "travail",
                "relation",
                "emotion",
                "habitude",
            ])
            .order("created_at", desc=False)
            .execute()
        )

        rows = result.data or []

        for row in rows:
            t = row.get("type")
            v = row.get("messages")

            if t and v:
                facts[t] = v

    except Exception as e:
        print("ERREUR get_user_facts:", e)

    return facts


def save_structured_fact(user_id: str, fact_type: str, fact_value: str):
    try:
        existing_fact = (
            supabase.table("memories")
            .select("messages")
            .eq("user_id", user_id)
            .eq("type", fact_type)
            .eq("messages", fact_value)
            .execute()
        )

        if not existing_fact.data:
            save_memory(user_id, "system", fact_value, "neutre", fact_type)

    except Exception as e:
        print("ERREUR save_structured_fact:", e)


def build_proactive_hint(message: str, facts: dict) -> str:
    normalized = normalize_text(message).lower()

    small_talk_inputs = [
        "salut",
        "bonjour",
        "yo",
        "ça va",
        "ca va",
        "hello",
        "coucou",
    ]

    if normalized in small_talk_inputs:
        if facts.get("objectif"):
            return f"Tu peux relancer naturellement l'utilisateur sur son objectif actuel, qui est de {facts['objectif']}."
        if facts.get("preference"):
            return f"L'utilisateur préfère {facts['preference']}. Tu peux t'appuyer dessus naturellement dans ta réponse."
        return ""

    vague_inputs = [
        "ok",
        "oui",
        "non",
        "d'accord",
        "ça marche",
        "vas-y",
        "go",
    ]

    if normalized in vague_inputs and facts.get("objectif"):
        return f"Tu peux relancer l'utilisateur sur son objectif actuel : {facts['objectif']}."

    return ""


def get_latest_user_message_time(user_id: str):
    try:
        result = (
            supabase.table("memories")
            .select("created_at")
            .eq("user_id", user_id)
            .eq("role", "user")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        rows = result.data or []

        if rows:
            return parse_iso_date(rows[0].get("created_at"))

    except Exception as e:
        print("ERREUR get_latest_user_message_time:", e)

    return None


def has_pending_proactive_message(user_id: str) -> bool:
    try:
        result = (
            supabase.table("proactive_messages")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as e:
        print("ERREUR has_pending_proactive_message:", e)
        return False


def build_proactive_message(user_id: str, facts: dict):
    user_name = facts.get("user_name") or facts.get("name") or "toi"
    objectif = facts.get("objectif")
    preference = facts.get("preference")

    if has_pending_proactive_message(user_id):
        print("PROACTIVE déjà pending")
        return None

    latest_user_dt = get_latest_user_message_time(user_id)
    now_dt = datetime.now(timezone.utc)

    hours_since_last_user_msg = None

    if latest_user_dt:
        hours_since_last_user_msg = (now_dt - latest_user_dt).total_seconds() / 3600

    if hours_since_last_user_msg is not None:
        if hours_since_last_user_msg > 24:
            return f"{user_name}, ça fait longtemps. Tu veux qu’on reprenne doucement ?"
        if hours_since_last_user_msg > 6:
            return f"{user_name}, ça fait un moment. Tu veux reprendre ?"

    if objectif:
        return f"{user_name}, tu voulais finir KOÉ. Où en es-tu aujourd'hui ?"

    if preference:
        return f"{user_name}, je me souviens que tu préfères {preference}. On reprend ?"

    return f"{user_name}, je viens prendre de tes nouvelles. On reprend notre échange ?"


def create_proactive_message_if_needed(user_id: str):
    facts = get_user_facts(user_id)
    proactive_message = build_proactive_message(user_id, facts)

    if not proactive_message:
        return None

    try:
        result = (
            supabase.table("proactive_messages")
            .insert({
                "user_id": user_id,
                "messages": proactive_message,
                "status": "pending",
                "shown": False,
                "scheduled_for": now_utc_iso(),
            })
            .execute()
        )

        print("PROACTIVE MESSAGE CREATED:", proactive_message)
        return result.data

    except Exception as e:
        print("ERREUR create_proactive_message_if_needed:", e)
        return None


@app.get("/")
def root():
    return {"status": "KOÉ backend is running"}



@app.post("/realtime-session")
async def realtime_session():
    try:
        session = client.realtime.client_secrets.create(
            session={
                "type": "realtime",
                "model": "gpt-realtime",
                "audio": {
                    "output": {
                        "voice": "alloy"
                    }
                },
            instructions: """ Tu es KOÉ.
Tu réponds toujours en français.
Tu ne réponds jamais en japonais.
Tu ne réponds jamais en coréen.
Tu ne réponds jamais en portugais.
Tu ne réponds jamais en anglais.
Si tu détectes une autre langue ou du bruit audio, tu réponds en français :
"Je n'ai pas bien compris. Tu peux répéter ?"
Tu es un compagnon vocal calme, simple et naturel.
Tes réponses sont courtes, humaines et utiles""".`,
            }
        )
        print("REALTIME SESSION CREATED")
        return session.model_dump()

    except Exception as e:
        print("REALTIME SESSION ERROR:", e)
        return {
            "ok": False,
            "error": str(e)
        }
        
@app.post("/log-message")
async def log_message(payload: dict):
    try:
        supabase.table("messages").insert({
            "user_id": payload.get("user_id"),
            "role": payload.get("role"),
            "text": payload.get("content")
        }).execute()

        return {"ok": True}

       except Exception as e:
        print("LOG MESSAGE ERROR:", e)
        return {"ok": False, "error": str(e)}
        
            }

@app.post("/chat")
async def chat(data: dict):
    try:
        user_id = data.get("user_id", "default")
        message = data.get("message", "")
        emotion = data.get("emotion", "neutre")

        if not message or len(message.strip()) < 2:
            return {
                "ok": True,
                "answer": "Je n’ai pas bien entendu. Tu peux répéter ?"
            }

        normalized_message = normalize_text(message).lower()

        extracted_name = extract_name(message)

        if extracted_name:
            save_user_name(user_id, extracted_name)

        extracted_fact = extract_fact(message)

        if extracted_fact and extracted_fact.get("value"):
            save_structured_fact(
                user_id,
                extracted_fact["fact_type"],
                extracted_fact["value"]
            )

        user_name = get_user_name(user_id)
        facts = get_user_facts(user_id)

        if not user_name and facts.get("name"):
            user_name = facts.get("name")

        save_memory(user_id, "user", message, emotion)

        if (
            "comment je m'appelle" in normalized_message
            or "quel est mon prénom" in normalized_message
            or "tu te souviens de mon prénom" in normalized_message
        ):
            if user_name:
                answer = f"Tu t'appelles {user_name}."
            else:
                answer = "Je ne connais pas encore ton prénom."

            save_memory(user_id, "assistant", answer, "neutre")

            return {
                "ok": True,
                "answer": answer
            }

        if "quel est mon objectif" in normalized_message:
            if facts.get("objectif"):
                answer = f"Ton objectif actuel est de {facts['objectif']}."
            else:
                answer = "Je ne connais pas encore ton objectif."

            save_memory(user_id, "assistant", answer, "neutre")

            return {
                "ok": True,
                "answer": answer
            }

        history_response = (
    supabase.table("messages")
    .select("role,text")
    .eq("user_id", user_id)
    .order("created_at", desc=True)
    .limit(12)
    .execute()
)

history = history_response.data or []
history.reverse()

raw_memories = get_recent_memories(user_id, limit=30)

high_memories = [
    m for m in raw_memories
    if m.get("importance") == "high"
]

medium_memories = [
    m for m in raw_memories
    if m.get("importance") == "medium"
]

        conversation_memories = [
    m for m in raw_memories
    if (
        m.get("role") == "user"
        and m.get("type") == "conversation"
    )
]

        conversation_context = [
    {
        "role": "system",
        "content": """You are KOÉ.
You are a conversational voice companion.
You cannot see the user.
You do not have camera access.
Respond only to the latest user message.
Keep responses short, simple and useful."""
    },
    {
        "role": "user",
        "content": message
    }
]

        if user_name:
            conversation_context.append({
                "role": "system",
                "content": f"L'utilisateur s'appelle {user_name}.",
            })

        for mem in high_memories[-10:]:
            if mem.get("messages"):
                conversation_context.append({
                    "role": "system",
                    "content": f"Mémoire importante utilisateur : {mem.get('messages')}"
                })
                

        for mem in medium_memories[-5:]:
            if mem.get("messages"):
                conversation_context.append({
                    "role": "system",
                    "content": f"Contexte utilisateur utile : {mem.get('messages')}"
                })

        for mem in conversation_memories[-10:]:
            conversation_context.append({
                "role": mem.get("role"),
                "content": mem.get("messages")
            })

        for msg in history:
            if (
                msg.get("role") in ["user", "assistant"]
                and msg.get("text")
            ):
                conversation_context.append({
                    "role": msg.get("role"),
                    "content": msg.get("text")
                })

        proactive_hint = build_proactive_hint(message, facts)

        if proactive_hint:
            conversation_context.append({
                "role": "system",
                "content": proactive_hint,
            })

        conversation_context.append({
            "role": "user",
            "content": message
        })

        print("========== KOÉ CONVERSATION_CONTEXT ==========")
        print(conversation_context)
        print("=============================================")
        print("KOE_CONTEXT:", conversation_context)

        response = client.responses.create(
            model="gpt-5.5",
            input=conversation_context,
        )

        answer = response.output_text.strip()

        # save_memory(user_id, "assistant", answer, "neutre")

        return {
    "ok": True,
    "answer": "TEST BACKEND"
}

    except Exception as e:
        print("ERREUR BACKEND GLOBALE:", e)

        return {
            "ok": False,
            "answer": "",
            "error": str(e)
        }

"""
# LEGACY ROUTE - TO REMOVE
@app.post("/chat-voice")
async def chat_voice(data: dict):
    try:
        text = (
            data.get("message")
            or data.get("text")
            or data.get("answer")
            or ""
        ).strip()

        if not text:
            text = "Je n'ai pas bien entendu. Tu peux répéter ?"

        tmp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp_audio_path = tmp_audio.name
        tmp_audio.close()

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text,
            response_format="mp3"
        ) as response:
            response.stream_to_file(tmp_audio_path)

        return FileResponse(
            tmp_audio_path,
            media_type="audio/mpeg",
            filename="koe-chat.mp3"
        )

    except Exception as e:
        print("CHAT VOICE ERROR:", e)
        return {
            "ok": False,
            "error": str(e),
            "answer": "KOÉ rencontre un problème pour parler maintenant."
        }
    """
@app.post("/voice-message")
async def voice_message(
    audio: UploadFile = File(...),
    user_id: str = Form("default")
):
    try:
        suffix = os.path.splitext(audio.filename or "")[-1] or ".webm"
        audio_bytes = await audio.read()

        if not audio_bytes or len(audio_bytes) < 1000:
            print("AUDIO TOO SMALL OR EMPTY")
            fallback_text = "Je n’ai pas bien entendu. Tu peux répéter ?"
            return await generate_voice_response(fallback_text, "", fallback_text, "audio_empty")

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            audio_path = tmp.name

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                language="fr"
            )

        text = (getattr(transcript, "text", "") or "").strip()

        if not text:
            text = "Je n’ai pas bien entendu. Tu peux répéter ?"

        chat_result = await chat({
            "message": text,
            "user_id": user_id,
            "emotion": "neutre"
        })

        answer = (chat_result.get("answer", "") if chat_result else "").strip()

        if not answer:
            answer = "Je suis là, mais j’ai eu du mal à répondre clairement."

        return await generate_voice_response(answer, text, answer)

    except Exception as e:
        print("VOICE MESSAGE ERROR:", e)
        fallback_text = "KOÉ rencontre un problème pour traiter ta voix maintenant."
        return await generate_voice_response(fallback_text, "", fallback_text, str(e))


async def generate_voice_response(answer: str, transcript: str = "", header_answer: str = "", error: str = ""):
    try:
        tmp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp_audio_path = tmp_audio.name
        tmp_audio.close()

        safe_answer = normalize_text(answer)
        safe_transcript = normalize_text(transcript)

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=safe_answer,
            response_format="mp3"
        ) as response:
            response.stream_to_file(tmp_audio_path)

        headers = {
            "X-KOE-Transcript": quote(safe_transcript),
            "X-KOE-Answer": quote(header_answer or safe_answer),
        }

        if error:
            headers["X-KOE-Error"] = quote(str(error))

        return FileResponse(
            tmp_audio_path,
            media_type="audio/mpeg",
            headers=headers,
            filename="koe-response.mp3"
        )

    except Exception as tts_error:
        print("VOICE RESPONSE TTS ERROR:", tts_error)
        return {
            "ok": False,
            "error": str(tts_error),
            "answer": answer
        }

@app.post("/tts")
def tts(data: dict):
    try:
        text = data.get("text", "")

        if not text:
            return {
                "ok": False,
                "error": "No text provided"
            }

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp_path = tmp.name
        tmp.close()

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text,
            response_format="mp3"
        ) as response:
            response.stream_to_file(tmp_path)

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg"
        )

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


@app.get("/proactive-message")
def get_proactive_message(user_id: str):
    try:
        if not user_id or user_id == "default":
            return {
                "ok": False,
                "error": "Missing or invalid user_id"
            }

        result = (
            supabase.table("proactive_messages")
            .select("*")
            .eq("user_id", user_id)
            .eq("shown", False)
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )

        return {
            "ok": True,
            "data": result.data[0] if result.data else None
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


@app.post("/mark-proactive-shown")
def mark_proactive_shown(data: dict):
    try:
        message_id = data.get("id")

        if not message_id:
            return {
                "ok": False,
                "error": "Missing message id"
            }

        result = (
            supabase.table("proactive_messages")
            .update({"shown": True})
            .eq("id", message_id)
            .execute()
        )

        return {
            "ok": True,
            "data": result.data
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


@app.post("/run-proactive-check")
def run_proactive_check(data: dict):
    try:
        user_id = data.get("user_id")

        if not user_id or user_id == "default":
            return {
                "ok": False,
                "error": "Missing or invalid user_id"
            }

        user_name = get_user_name(user_id)
        facts = get_user_facts(user_id)

        if user_name:
            facts["user_name"] = user_name

        message = build_proactive_message(user_id, facts)

        if not message:
            return {
                "ok": True,
                "created": False,
                "data": None
            }

        result = (
            supabase.table("proactive_messages")
            .insert({
                "user_id": user_id,
                "message": message,
                "shown": False,
                "status": "pending",
            })
            .execute()
        )

        return {
            "ok": True,
            "created": True,
            "data": result.data
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
        
@app.post("/chat-pdf")
async def chat_pdf(
    user_id: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...)
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        reader = PdfReader(tmp_path)
        text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    finally:
        os.unlink(tmp_path)

    if not text:
        return {
            "ok": True,
            "answer": "Je reçois le PDF, mais je n'arrive pas à en extraire le texte."
        }

    text = text[:12000]
    full_message = f"[Contenu du PDF]\n{text}\n\n[Message utilisateur]\n{message}"

    return await chat({
        "message": full_message,
        "user_id": user_id,
        "emotion": "neutre"
    })        
