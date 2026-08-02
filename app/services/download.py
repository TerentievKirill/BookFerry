
import requests
import os
from app.services.opds import Book



def download_book(book: Book) -> str:
    response = requests.get(book.url, timeout=30)
    response.raise_for_status()

    temp_dir = os.path.join(os.getcwd(), "Temp")
    os.makedirs(temp_dir, exist_ok=True)

    raw_header = response.headers["Content-Disposition"]

    # Удаляем двойные кавычки с краёв строки после разделения
    filename = raw_header.split("filename=")[1].strip('"')


    print(filename)
    path = os.path.join(temp_dir, filename)

    with open(path, "wb") as f:
        f.write(response.content)

    return path

def remove_book(path):
    if os.path.exists(path):
        os.remove(path)
