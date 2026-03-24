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

client = OpenAI(api_key=os.getenv("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") or "")

SYSTEM_PROMPT = """
Tu es KOÉ, une intelligence calme, élégante et humaine.
Tu réponds avec simplicité, clarté et profondeur.
Tu ne répètes jamais l’utilisateur.
Tu engages la conversation naturellement.
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
