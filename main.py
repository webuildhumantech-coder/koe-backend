import os
import re
import tempfile
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from supabase import create_client
from openai import OpenAI


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

Règle importante :
Tu ne dois jamais appeler l'utilisateur Souleymane sauf si son profil utilisateur propre indique explicitement que son prénom est Souleymane.
Si tu ne connais pas son prénom, ne devine pas.
"""


# ========================
# OUTILS MÉMOIRE
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


def get_recent_memories(user_id: str, limit=12):
    try:
        result = (
            supabase.table("memories")
            .select("role,message,created_at,type")
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
        supabase.table("memories").insert({
            "user_id": user_id,
            "message": message,
            "emotion": emotion,
            "role": role,
            "type": memory_type,
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
            .select("message")
            .eq("user_id", user_id)
            .eq("type", "name")
            .eq("message", name)
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
            .select("message,type")
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


def save_structured_fact(user_id: str, fact_type: str, fact_value: str):
    try:
        existing_fact = (
            supabase.table("memories")
            .select("message")
            .eq("user_id", user_id)
            .eq("type", fact_type)
            .eq("message", fact_value)
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


# ========================
# PROACTIF
# ========================

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
                "message": proactive_message,
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


# ========================
# ROUTES
# ========================

@app.get("/")
def root():
    return {"status": "KOÉ backend is running"}


@app.post("/chat")
async def chat(data: dict):
    try:
        message = data.get("message", "").strip()
        user_id = data.get("user_id")
        emotion = "neutre"

        print("CHAT USER_ID:", user_id)

        if not user_id:
            return {
                "ok": False,
                "answer": "",
                "error": "Missing user_id"
            }

        if user_id == "default":
            return {
                "ok": False,
                "answer": "",
                "error": "Invalid user_id"
            }

        if not message:
            return {
                "ok": False,
                "answer": "",
                "error": "No message provided"
            }

        normalized_message = normalize_text(message).lower()

        # 1) Détection prénom
        extracted_name = extract_name(message)
        if extracted_name:
            save_user_name(user_id, extracted_name)

        # 2) Détection faits
        extracted_fact = extract_fact(message)
        if extracted_fact and extracted_fact.get("value"):
            save_structured_fact(
                user_id,
                extracted_fact["fact_type"],
                extracted_fact["value"],
            )

        # 3) Lecture profil/faits
        user_name = get_user_name(user_id)
        facts = get_user_facts(user_id)

        if not user_name and facts.get("name"):
            user_name = facts.get("name")

        # 4) Sauvegarde message utilisateur
        save_memory(user_id, "user", message, emotion)

        # 5) Réponses directes
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

        if (
            "quand est-ce que je préfère parler" in normalized_message
            or "je préfère parler quand" in normalized_message
        ):
            if facts.get("preference"):
                answer = f"Tu préfères {facts['preference']}."
            else:
                answer = "Je ne connais pas encore ta préférence."

            save_memory(user_id, "assistant", answer, "neutre")
            return {
                "ok": True,
                "answer": answer
            }

        # 6) Lecture mémoire récente
        raw_memories = get_recent_memories(user_id, limit=30)

        conversation_context = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        if user_name:
            conversation_context.append({
                "role": "system",
                "content": f"L'utilisateur s'appelle {user_name}.",
            })

        if facts.get("objectif"):
            conversation_context.append({
                "role": "system",
                "content": f"L'objectif actuel de l'utilisateur est de {facts['objectif']}.",
            })

        if facts.get("preference"):
            conversation_context.append({
                "role": "system",
                "content": f"L'utilisateur préfère {facts['preference']}.",
            })

        proactive_hint = build_proactive_hint(message, facts)
        if proactive_hint:
            conversation_context.append({
                "role": "system",
                "content": proactive_hint,
            })

        conversation_memories = [
            m for m in raw_memories
            if m.get("role") in ["user", "assistant"]
            and m.get("message")
            and m.get("type") == "conversation"
        ]

        for mem in conversation_memories[-10:]:
            conversation_context.append({
                "role": mem.get("role"),
                "content": mem.get("message"),
            })

        conversation_context.append({
            "role": "user",
            "content": message,
        })

        # 7) Appel OpenAI
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=conversation_context,
        )

        answer = response.output_text.strip()

        # 8) Sauvegarde réponse assistant
        save_memory(user_id, "assistant", answer, "neutre")

        return {
            "ok": True,
            "answer": answer
        }

    except Exception as e:
        print("ERREUR BACKEND GLOBALE:", e)
        return {
            "ok": False,
            "answer": "",
            "error": str(e)
        }


@app.post("/chat-voice")
async def chat_voice(data: dict):
    try:
        chat_result = await chat(data)

        if not chat_result or not chat_result.get("ok"):
            return {
                "ok": False,
                "error": chat_result.get("error") if chat_result else "Chat returned nothing"
            }

        answer = chat_result.get("answer", "").strip()

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
        print("CHAT VOICE ERROR:", e)
        return {
            "ok": False,
            "error": str(e)
        }


@app.post("/tts")
def tts(data: dict):
    try:
        text = data.get("text", "")

        if not text:
            return {"ok": False, "error": "No text provided"}

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
            return {"ok": False, "error": "Missing message id"}

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