
import requests
import os



def download_book(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    temp_dir = os.path.join(os.getcwd(), "Temp")
    os.makedirs(temp_dir, exist_ok=True)

    raw_header = response.headers["Content-Disposition"]
    filename = raw_header.split("filename=")[1].strip('"')

    path = os.path.join(temp_dir, filename)

    with open(path, "wb") as file:
        file.write(response.content)

    return path

def remove_book(path):
    if os.path.exists(path):
        os.remove(path)
