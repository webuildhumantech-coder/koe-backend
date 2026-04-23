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
Tu réponds avec simplicité, clarté et profondeur.
Tu engages la conversation naturellement.
Quand une information fiable sur l’utilisateur est connue, tu peux t’en servir.
"""

# ========================
# OUTILS
# ========================

def extract_name(message: str):
    cleaned = message.replace("\\'", "'").replace("\\", "")
    match = re.search(r"je m['’]appelle\s+([A-Za-zÀ-ÿ\-]+)", cleaned, re.IGNORECASE)
    if match:
        return match.group(1).strip().capitalize()
    return None


def extract_fact(message: str):
    cleaned = message.replace("\\'", "'").replace("\\", "").strip()
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

        # 3) Sauvegarde prénom dans user_profile + memories
        if extracted_name and extracted_name.lower() not in ["none", "null", ""]:
            try:
                supabase.table("user_profile").upsert({
                    "user_id": user_id,
                    "name": extracted_name,
                }).execute()

                supabase.table("memories").insert({
                    "user_id": user_id,
                    "message": f"Le prénom de l'utilisateur est {extracted_name}",
                    "emotion": "neutre",
                    "role": "system",
                    "type": "fact",
                }).execute()

                print("USER PROFILE + NAME FACT OK")
            except Exception as e:
                print("ERREUR USER PROFILE / NAME FACT:", e)

        # 4) Sauvegarde autres faits
        if extracted_fact and extracted_fact.get("value"):
            try:
                fact_message = f"{extracted_fact['fact_type']}:{extracted_fact['value']}"

                supabase.table("memories").insert({
                    "user_id": user_id,
                    "message": fact_message,
                    "emotion": "neutre",
                    "role": "system",
                    "type": "fact",
                }).execute()

                print("FACT MEMORY OK")
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

            print("PROFILE DATA:", profile.data)

            if profile.data and len(profile.data) > 0:
                user_name = profile.data[0].get("name")
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

        # 7) Réponse directe si question sur le prénom
        normalized_message = message.replace("\\'", "'").replace("\\", "").lower()

        if (
            "comment je m'appelle" in normalized_message
            or "quel est mon prénom" in normalized_message
        ):
            if user_name:
                answer = f"Tu t'appelles {user_name}."
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

                print("INSERT ASSISTANT DIRECT OK")
            except Exception as e:
                print("ERREUR INSERT ASSISTANT DIRECT:", e)

            return {"answer": answer}

        # 8) Lecture des mémoires
        memories = []
        facts = []

        try:
            memory_result = (
                supabase.table("memories")
                .select("role, message, type")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )

            raw_memories = memory_result.data or []
            raw_memories.reverse()

            for mem in raw_memories:
                if mem.get("type") == "fact":
                    facts.append(mem)
                else:
                    memories.append(mem)

            print("MEMORIES COUNT:", len(memories))
            print("FACTS COUNT:", len(facts))
        except Exception as e:
            print("ERREUR LECTURE MEMORIES:", e)

        # 9) Construction du contexte
        conversation_context = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        if user_name:
            conversation_context.append({
                "role": "system",
                "content": f"L'utilisateur s'appelle {user_name}.",
            })

        for fact in facts[-5:]:
            content = fact.get("message")
            if content:
                conversation_context.append({
                    "role": "system",
                    "content": content,
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

        # 10) Appel OpenAI
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=conversation_context,
        )

        answer = response.output_text.strip()

        # 11) Sauvegarde réponse assistant
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