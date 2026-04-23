import os
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from openai import OpenAI

# ========================
# CONFIG
# ========================

SUPABASE_URL = "https://zxuysoqknkzjmpftqupl.supabase.co"
SUPABASE_KEY = "sb_publishable_rrh5vevB5bc5E1xauwOaPw_EyG3xSW8"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY") or "")

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

Règles importantes :

1. Si tu connais un objectif de l'utilisateur, tu dois t'y référer naturellement dans la conversation.
2. Si la conversation est légère (salut, ça va, etc.), tu peux relancer en lien avec cet objectif.
3. Tu ne forces jamais, tu proposes avec subtilité.
4. Tu donnes toujours une sensation de continuité.

Ton but :
Créer une présence vivante, pas juste répondre.

Style :
Simple, fluide, humain, jamais robotique.
"""

# ========================
# OUTILS
# ========================

def normalize_text(text: str) -> str:
    return text.replace("\\'", "'").replace("\\", "").strip()


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


def build_fact_message(extracted_fact: dict) -> str:
    fact_type = extracted_fact.get("fact_type")
    value = extracted_fact.get("value", "").strip()

    if fact_type == "objectif":
        return f"L'objectif actuel de l'utilisateur est de {value}."
    if fact_type == "preference":
        return f"L'utilisateur préfère {value}."

    return value


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
    """
    Petite couche proactive.
    Elle ne remplace pas la réponse principale, elle donne une direction.
    """
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

    # si préférence matin et échange matinal mentionné
    if "matin" in normalized and facts.get("preference"):
        return f"L'utilisateur préfère {facts['preference']}. Intègre cette préférence avec naturel."

    # si objectif existe et message vague
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
# ROUTES
# ========================

@app.get("/")
def root():
    return {"status": "KOÉ backend is running"}


@app.post("/chat")
async def chat(data: dict):
    try:
        message = data.get("message", "").strip()
        user_id = "default"
        emotion = "neutre"

        if not message:
            return {"answer": "No message"}

        print("MESSAGE RECU:", repr(message))

        # 1) Détection prénom
        extracted_name = extract_name(message)
        print("EXTRACTED NAME:", extracted_name)

        # 2) Détection autres faits
        extracted_fact = extract_fact(message)
        print("EXTRACTED FACT:", extracted_fact)

        # 3) Sauvegarde prénom dans user_profile + fact
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

                print("USER PROFILE + NAME FACT OK")

            except Exception as e:
                print("ERREUR USER PROFILE / NAME FACT:", e)

        # 4) Sauvegarde autres facts avec anti-doublon
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
                    print("FACT MEMORY OK")
                else:
                    print("FACT DEJA EXISTANT")

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

            print("PROFILE DATA:", profile.data)

        except Exception as e:
            print("ERREUR LECTURE USER_PROFILE:", e)

        print("USER_NAME AVANT REPONSE:", user_name)

        # 6) Sauvegarde message user
        try:
            supabase.table("memories").insert({
                "user_id": user_id,
                "message": message,
                "emotion": emotion,
                "role": "user",
                "type": "conversation",
            }).execute()

            print("INSERT USER MEMORY OK")

        except Exception as e:
            print("ERREUR INSERT USER MEMORY:", e)

        # 7) Facts structurés
        facts = get_user_facts(user_id)
        print("FACTS STRUCTURES:", facts)

        # 8) Réponses directes ciblées
        normalized_message = normalize_text(message).lower()

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

            print("MEMORIES COUNT:", len(memories))
            print("FACT ROWS COUNT:", len(fact_rows))

        except Exception as e:
            print("ERREUR LECTURE MEMORIES:", e)

        # 10) Contexte proactif
        proactive_hint = build_proactive_hint(message, facts)
        print("PROACTIVE HINT:", proactive_hint)

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

        print("CONTEXT READY")

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

            print("INSERT ASSISTANT MEMORY OK")

        except Exception as e:
            print("ERREUR INSERT ASSISTANT MEMORY:", e)

        return {"answer": answer}

    except Exception as e:
        print("ERREUR BACKEND GLOBALE:", e)
        return {"answer": f"Erreur backend : {str(e)}"}