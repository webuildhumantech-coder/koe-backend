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

Quand une information fiable sur l’utilisateur est connue
(exemple : son prénom), tu dois t’en servir si la question s’y rapporte.
"""

# ========================
# OUTILS
# ========================

def extract_name(message: str):
    message = message.lower()

    patterns = [
        r"je m['’]appelle\s+([a-zà-ÿ\-]+)",
        r"mon prénom est\s+([a-zà-ÿ\-]+)",
        r"c['’]est\s+([a-zà-ÿ\-]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1).capitalize()

    return None
    extracted_name = extract_name(message)
    
    print(">>> EXTRACTED NAME:", extracted_name)

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

        # 1) Détecter un prénom
        extracted_name = extract_name(message)
        print("EXTRACTED NAME:", extracted_name)

        # 2) Sauvegarder le prénom dans user_profile si détecté
        if extracted_name:
         if extracted_name and extracted_name.lower() not in ["none", "null", ""]:
    
    # sauvegarde profil
            supabase.table("user_profile").upsert({
        "user_id": user_id,
        "name": extracted_name
    }).execute()

    # sauvegarde mémoire fact
    supabase.table("memories").insert({
        "user_id": user_id,
        "message": f"Le prénom de l'utilisateur est {extracted_name}",
        "emotion": "neutre",
        "role": "system",
        "type": "fact"
    }).execute()

        # 3) Relire user_profile
    user_name = None
    try:
            profile = supabase.table("user_profile")\
                .select("user_id, name")\
                .eq("user_id", user_id)\
                .execute()

            print("PROFILE DATA:", profile.data)

            if profile.data and len(profile.data) > 0:
                user_name = profile.data[0].get("name")
    except Exception as e:
            print("ERREUR LECTURE USER_PROFILE:", e)

    print("USER_NAME AVANT REPONSE:", user_name)

        # 4) Sauvegarder le message user dans memories
    try:
            supabase.table("memories").insert({
    "user_id": user_id,
    "message": f"Le prénom de l'utilisateur est {extracted_name}",
    "emotion": "neutre",
    "role": "system",
    "type": "fact"
}).execute()
            print("INSERT USER MEMORY OK")
    except Exception as e:
            print("ERREUR INSERT USER MEMORY:", e)

        # 5) Réponse directe si on demande le prénom
    normalized_message = message.replace("\\'", "'").replace("\\", "").lower()

    if "comment je m'appelle" in normalized_message or "quel est mon prénom" in normalized_message or "mon prénom" in normalized_message:
            if user_name:
                answer = f"Tu t'appelles {user_name}."
            else:
                answer = "Je ne connais pas encore ton prénom."

            try:
                supabase.table("memories").insert({
    "user_id": user_id,
    "message": message,
    "role": "user",
    "type": "conversation"
}).execute()
                print("INSERT ASSISTANT DIRECT OK")
            except Exception as e:
                print("ERREUR INSERT ASSISTANT DIRECT:", e)

            return {"answer": answer}

        # 6) Lire les derniers messages de mémoire
    memories = []
    try:
            memory_result = supabase.table("memories")\
                .select("role, message")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .limit(10)\
                .execute()

            memories = memory_result.data or []
            memories.reverse()
            print("MEMORIES COUNT:", len(memories))
    except Exception as e:
            print("ERREUR LECTURE MEMORIES:", e)

        # 7) Construire le contexte
    conversation_context = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    if user_name:
            conversation_context.append({
                "role": "system",
                "content": f"L'utilisateur s'appelle {user_name}."
            })

    for mem in memories:
            role = mem.get("role")
            content = mem.get("message")
            if role in ["user", "assistant"] and content:
                conversation_context.append({
                    "role": role,
                    "content": content
                })

    conversation_context.append({
            "role": "user",
            "content": message
        })

    print("CONTEXT READY")

        # 8) Appel OpenAI
    response = client.responses.create(
            model="gpt-4.1-mini",
            input=conversation_context
        )

    answer = response.output_text.strip()

        # 9) Sauvegarder la réponse assistant
    try:
            supabase.table("memories").insert({
    "user_id": user_id,
    "message": answer,
    "role": "assistant",
    "type": "conversation"
}).execute()
            print("INSERT ASSISTANT MEMORY OK")
    except Exception as e:
            print("ERREUR INSERT ASSISTANT MEMORY:", e)

    return {"answer": answer}

    except Exception as e:
print("ERREUR BACKEND GLOBALE:", e)
return {"answer": f"Erreur backend : {str(e)}"}