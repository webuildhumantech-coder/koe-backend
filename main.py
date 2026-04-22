from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import os
from supabase import create_client

SUPABASE_URL = "https://zxuysoqknkzjmpftqupl.supabase.co"
SUPABASE_KEY = "sb_publishable_rrh5vevB5bc5E1xauwOaPw_EyG3xSW8"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY") or "")

SYSTEM_PROMPT = """
Tu es KOÉ, une intelligence calme, élégante et humaine.
Tu réponds avec simplicité, clarté et profondeur.
Tu ne répètes jamais l’utilisateur.
Tu engages la conversation naturellement.
"""
print("SUPABASE TEST LIVE")

@app.post("/chat")
async def chat(data: dict):
    try:
        message = data.get("message", "").strip()

        if not message:
            return {"answer": "No message"}

        emotion = "neutre"

        try:
            supabase.table("memories").insert({
    "user_id": "default",
    "message": message,
    "emotion": emotion,
    "role": "user"
}).execute()
            print("INSERT SUPABASE OK")
        except Exception as e:
            print("ERREUR SUPABASE :", e)

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
        )

        answer = response.output_text.strip()
        supabase.table("memories").insert({
    "user_id": "default",
    "message": answer,
    "emotion": "neutre",
    "role": "assistant"
}).execute()

        return {"answer": answer}

    except Exception as e:
        return {"answer": f"Erreur backend : {str(e)}"}
