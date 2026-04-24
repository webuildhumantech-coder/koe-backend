import os
import re
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from openai import OpenAI
from fastapi.responses import Response
from fastapi.responses import FileResponse
import tempfile

# ========================
# CONFIG
# ========================

SUPABASE_URL = "https://zxuysoqknkzjmpftqupl.supabase.co"
SUPABASE_KEY = "sb_publishable_rrh5vevB5bc5E1xauwOaPw_EyG3xSW8"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SYSTEM_PROMPT = """
Tu es KOÉ, une intelligence calme, élégante et humaine.
Tu réponds avec simplicité, clarté et profondeur.
Tu engages la conversation naturellement.
"""

# ========================
# OUTILS
# ========================

def normalize_text(text: str) -> str:
    return text.replace("\\'", "'").replace("\\", "").strip()


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
        (r"je préfère\s+(.+)", "preference"),
        (r"j'aime\s+(.+)", "preference"),
    ]

    for pattern, fact_type in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return {
                    "fact_type": fact_type,
                    "value": value,
                }

    return None

def get_user_facts(user_id: str) -> dict:
    facts = {}

    try:
        result = (
            supabase.table("memories")
            .select("message, type")
            .eq("user_id", user_id)
            .in_("type", ["name", "objectif", "preference"])
            .order("created_at", desc=False)
            .execute()
        )

        rows = result.data or []

        for row in rows:
            t = row.get("type")
            v = row.get("message")

            if t == "name" and v:
                facts["name"] = v
            elif t == "objectif" and v:
                facts["objectif"] = v
            elif t == "preference" and v:
                facts["preference"] = v

    except Exception as e:
        print("ERREUR get_user_facts:", e)

    return facts

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
    user_name = facts.get("user_name") or "toi"
    objectif = facts.get("objectif")
    preference = facts.get("preference")

    if has_pending_proactive_message(user_id):
        print("PROACTIVE déjà pending")
        return None

    if objectif:
        return f"{user_name}, tu voulais finir KOÉ. Où en es-tu aujourd'hui ?"

    if preference:
        return f"{user_name}, je me souviens que tu préfères {preference}. On reprend ?"

    return f"{user_name}, je viens prendre de tes nouvelles. On reprend notre échange ?"

    if has_pending_proactive_message(user_id):
        print("PROACTIVE déjà pending")
        return None

    latest_user_dt = get_latest_user_message_time(user_id)
    now_dt = datetime.now(timezone.utc)

    if hours_since_last_user_msg is not None:
     if hours_since_last_user_msg > 24:
        return f"{user_name}, ça fait longtemps. Tu veux qu’on reprenne doucement ?"
    elif hours_since_last_user_msg > 6:
        return f"{user_name}, ça fait un moment. Tu veux reprendre ?"
    
    # Règles simples de départ
    # 1) si objectif connu et plus de 12h sans message user
    if objectif:
     return f"{user_name}, tu voulais finir KOÉ. Où en es-tu aujourd'hui ?"

    # 2) si préférence matin connue et aucun message récent (>12h)
    current_hour_utc = now_dt.hour
    is_morning_utc = 6 <= current_hour_utc <= 11

    if preference and "matin" in preference.lower() and hours_since_last_user_msg is not None and hours_since_last_user_msg >= 12 and is_morning_utc:
        return f"{user_name}, comme tu préfères parler le matin, c'est peut-être un bon moment pour reprendre notre échange."

    return None


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
                "message": proactive_message,
                "status": "pending",
                "scheduled_for": now_utc_iso(),
            })
            .execute()
        )
        print("PROACTIVE MESSAGE CREATED:", proactive_message)
        return result.data
    except Exception as e:
        print("ERREUR create_proactive_message_if_needed:", e)
        return None

# ========================
# ROUTES
# ========================
def get_user_name(user_id):
    result = supabase.table("user_profile") \
        .select("name") \
        .eq("user_id", user_id) \
        .execute()

    if result.data and len(result.data) > 0:
        return result.data[0]["name"]

    return None


@app.get("/")
def root():
    return {"status": "KOÉ backend is running"}


@app.get("/proactive-message")
def get_proactive_message(user_id: str = "default"):
    try:
        result = supabase.table("proactive_messages") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("shown", False) \
            .order("created_at", desc=False) \
            .limit(1) \
            .execute()

        return {
            "ok": True,
            "data": result.data[0] if result.data else None
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }

        rows = result.data or []
        if not rows:
            return {"message": None}

        row = rows[0]
        return {"message": row}

    except Exception as e:
        print("ERREUR /proactive-message:", e)
        return {"message": None, "error": str(e)}


@app.post("/mark-proactive-shown")
def mark_proactive_shown(data: dict):
    try:
        message_id = data.get("id")

        if not message_id:
            return {"ok": False, "error": "Missing message id"}

        result = supabase.table("proactive_messages") \
            .update({"shown": True}) \
            .eq("id", message_id) \
            .execute()

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
def run_proactive_check():
    try:
        user_id = "default"

        user_name = get_user_name(user_id)

        facts = {
            "user_name": user_name
        }

        message = build_proactive_message(user_id, facts)

        if not message:
            return {
                "ok": True,
                "created": False,
                "data": None
            }

        result = supabase.table("proactive_messages").insert({
            "user_id": user_id,
            "message": message,
            "shown": False
        }).execute()

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
from fastapi.responses import StreamingResponse
import io

from fastapi.responses import StreamingResponse
from openai import OpenAI
import io
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

from fastapi.responses import FileResponse
import tempfile
import os

@app.post("/tts")
def tts(data: dict):
    text = data.get("text", "")

    if not text:
        return {"ok": False, "error": "No text provided"}

    try:
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

        print("TTS FILE SIZE:", os.path.getsize(tmp_path))

        return FileResponse(
            tmp_path,
            media_type="audio/mpeg",
            filename="koe.mp3"
        )

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
    
@app.post("/chat")
async def chat(data: dict):
    try:
        message = data.get("message", "").strip()
        user_id = "default"
        emotion = "neutre"

        if not message:
            return {
                "ok": True,
                "created": False,
                "data": None
            }

            response = client.responses.create(
            model="gpt-4.1-mini",
            input=f"""
{SYSTEM_PROMPT}

Utilisateur : {message}
"""
)
            answer = response.output_text.strip()

            return {"answer": answer}

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
    
@app.post("/chat-voice")
async def chat_voice(data: dict):
    try:
        chat_result = await chat(data)

        answer = chat_result.get("answer") or chat_result.get("data") or ""

        print("ANSWER:", answer)

        if not answer:
            return {
                "ok": False,
                "error": "No answer generated"
            }

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp_path = tmp.name
        tmp.close()

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=answer,
            response_format="mp3"
        ) as response:
            response.stream_to_file(tmp_path)

        print("CHAT VOICE SIZE:", os.path.getsize(tmp_path))

        return FileResponse(
            tmp_path,
            media_type="audio/mpeg",
            filename="koe-chat.mp3"
        )

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
        print("MESSAGE RECU:", repr(message))

        # 1) Détection prénom
        extracted_name = extract_name(message)
        print("EXTRACTED NAME:", extracted_name)

        # 2) Détection autres faits
        extracted_fact = extract_fact(message)
        print("EXTRACTED FACT:", extracted_fact)

        # 3) Sauvegarde prénom
        if extracted_name and extracted_name.lower() not in ["none", "null", ""]:
            try:
                supabase.table("user_profile").upsert({
                    "user_id": user_id,
                    "name": extracted_name,
                }).execute()

                existing_name_fact = (
                    supabase.table("memories")
                    .select("message")
                    .eq("user_id", user_id)
                    .eq("type", "name")
                    .eq("message", extracted_name)
                    .execute()
                )

                if not existing_name_fact.data:
                    supabase.table("memories").insert({
                        "user_id": user_id,
                        "message": extracted_name,
                        "emotion": "neutre",
                        "role": "system",
                        "type": "name",
                    }).execute()

            except Exception as e:
                print("ERREUR USER PROFILE / NAME FACT:", e)

        # 4) Sauvegarde facts
        if extracted_fact and extracted_fact.get("value"):
            try:
                fact_type = extracted_fact["fact_type"]
                fact_value = extracted_fact["value"]

                existing_fact = (
                    supabase.table("memories")
                    .select("message")
                    .eq("user_id", user_id)
                    .eq("type", fact_type)
                    .eq("message", fact_value)
                    .execute()
                )

                if not existing_fact.data:
                    supabase.table("memories").insert({
                        "user_id": user_id,
                        "message": fact_value,
                        "emotion": "neutre",
                        "role": "system",
                        "type": fact_type,
                    }).execute()

            except Exception as e:
                print("ERREUR FACT MEMORY:", e)

        # 5) Lecture user_profile
        user_name = None
        try:
            profile = (
                supabase.table("user_profile")
                .select("user_id, name")
                .eq("user_id", user_id)
                .execute()
            )

            if profile.data and len(profile.data) > 0:
                user_name = profile.data[0].get("name")

        except Exception as e:
            print("ERREUR LECTURE USER_PROFILE:", e)

        # 6) Sauvegarde message user
        try:
            supabase.table("memories").insert({
                "user_id": user_id,
                "message": message,
                "emotion": emotion,
                "role": "user",
                "type": "conversation",
            }).execute()

        except Exception as e:
            print("ERREUR INSERT USER MEMORY:", e)

        # 7) Facts structurés
        facts = get_user_facts(user_id)
        normalized_message = normalize_text(message).lower()

        # 8) Réponses directes
        if (
            "comment je m'appelle" in normalized_message
            or "quel est mon prénom" in normalized_message
        ):
            if user_name:
                answer = f"Tu t'appelles {user_name}."
            elif facts.get("name"):
                answer = f"Tu t'appelles {facts['name']}."
            else:
                answer = "Je ne connais pas encore ton prénom."

            try:
                supabase.table("memories").insert({
                    "user_id": user_id,
                    "message": answer,
                    "emotion": "neutre",
                    "role": "assistant",
                    "type": "conversation",
                }).execute()
            except Exception as e:
                print("ERREUR INSERT ASSISTANT DIRECT PRENOM:", e)

            return {"answer": answer}

        if "quel est mon objectif" in normalized_message:
            if facts.get("objectif"):
                answer = f"Ton objectif actuel est de {facts['objectif']}."
            else:
                answer = "Je ne connais pas encore ton objectif."

            try:
                supabase.table("memories").insert({
                    "user_id": user_id,
                    "message": answer,
                    "emotion": "neutre",
                    "role": "assistant",
                    "type": "conversation",
                }).execute()
            except Exception as e:
                print("ERREUR INSERT ASSISTANT DIRECT OBJECTIF:", e)

            return {"answer": answer}

        if (
            "quand est-ce que je préfère parler" in normalized_message
            or "je préfère parler quand" in normalized_message
        ):
            if facts.get("preference"):
                answer = f"Tu préfères parler {facts['preference']}."
            else:
                answer = "Je ne connais pas encore ta préférence."

            try:
                supabase.table("memories").insert({
                    "user_id": user_id,
                    "message": answer,
                    "emotion": "neutre",
                    "role": "assistant",
                    "type": "conversation",
                }).execute()
            except Exception as e:
                print("ERREUR INSERT ASSISTANT DIRECT PREFERENCE:", e)

            return {"answer": answer}

        # 9) Lecture des mémoires
        memories = []
        fact_rows = []

        try:
            memory_result = (
                supabase.table("memories")
                .select("role, message, type")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(30)
                .execute()
            )

            raw_memories = memory_result.data or []
            raw_memories.reverse()

            for mem in raw_memories:
                if mem.get("type") in ["name", "objectif", "preference"]:
                    fact_rows.append(mem)
                else:
                    memories.append(mem)

        except Exception as e:
            print("ERREUR LECTURE MEMORIES:", e)

        # 10) Contexte proactif
        proactive_hint = build_proactive_hint(message, facts)

        conversation_context = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        if user_name:
            conversation_context.append({
                "role": "system",
                "content": f"L'utilisateur s'appelle {user_name}.",
            })

        for fact in fact_rows[-8:]:
            t = fact.get("type")
            v = fact.get("message")

            if t == "name" and v:
                content = f"L'utilisateur s'appelle {v}."
            elif t == "objectif" and v:
                content = f"L'objectif actuel de l'utilisateur est de {v}."
            elif t == "preference" and v:
                content = f"L'utilisateur préfère {v}."
            else:
                continue

            conversation_context.append({
                "role": "system",
                "content": content,
            })

        if proactive_hint:
            conversation_context.append({
                "role": "system",
                "content": proactive_hint,
            })

        for mem in memories[-8:]:
            role = mem.get("role")
            content = mem.get("message")
            if role in ["user", "assistant"] and content:
                conversation_context.append({
                    "role": role,
                    "content": content,
                })

        conversation_context.append({
            "role": "user",
            "content": message,
        })

        # 11) Appel OpenAI
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=conversation_context,
        )

        answer = response.output_text.strip()

        # 12) Sauvegarde réponse assistant
        try:
            supabase.table("memories").insert({
                "user_id": user_id,
                "message": answer,
                "emotion": "neutre",
                "role": "assistant",
                "type": "conversation",
            }).execute()

        except Exception as e:
            print("ERREUR INSERT ASSISTANT MEMORY:", e)

        return {"answer": answer}

    except Exception as e:
        print("ERREUR BACKEND GLOBALE:", e)
        return {"answer": f"Erreur backend : {str(e)}"}
    