from .upload import get_service


def main():
    print("Opening browser for Google authorization...")
    yt = get_service()
    resp = yt.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if items:
        print("Authorized OK. Channel:", items[0]["snippet"]["title"])
        print("token.json saved -- future runs need no browser.")
    else:
        print("Authorized, but no YouTube channel is attached to this Google account.")
        print("Create a channel at youtube.com first, then re-run.")


if __name__ == "__main__":
    main()
