"""Convenience entrypoint: python main.py starts the Atlas API."""
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000)
