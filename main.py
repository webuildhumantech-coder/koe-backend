from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "KOÉ backend is running"}

@app.post("/chat")
async def chat(data: dict):
    message = data.get("message", "")
    return {"answer": f"KOÉ a entendu : {message}"}