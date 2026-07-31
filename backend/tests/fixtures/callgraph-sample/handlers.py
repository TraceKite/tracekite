from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return build_response()


def build_response():
    return {"status": "ok"}
