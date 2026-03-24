from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("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")

SYSTEM_PROMPT = """
Tu es KOÉ, une intelligence calme, élégante et humaine.
Tu réponds avec simplicité, naturel et profondeur.
Tu ne répètes jamais l’utilisateur.
Tu engages la conversation.
"""

@app.get("/")
def root():
    return {"status": "KOÉ backend is running"}

@app.post("/chat")
async def chat(data: dict):
    try:
        message = data.get("message", "").strip()

        if not message:
            return {"answer": "Je suis là."}

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
        )

        answer = response.output_text.strip() if response.output_text else "Je suis là."
        return {"answer": answer}

    except Exception as e:
        return {"answer": f"Erreur backend : {str(e)}"}
