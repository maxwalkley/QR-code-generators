# app.py
# pip install -r requirements.txt
from io import BytesIO
from pathlib import Path

import streamlit as st
import qrcode
from qrcode.constants import ERROR_CORRECT_L
from PIL import Image, ImageDraw

# ---------- vCard helpers ----------

def escape(val: str | None) -> str | None:
    if not val:
        return None
    return (val.replace("\\", "\\\\")
               .replace(";", r"\;")
               .replace(",", r"\,")
               .replace("\n", r"\n")
               .strip())

def buildVcard(firstName, lastName, org, phone, email, url) -> str:
    firstName, lastName = escape(firstName) or "", escape(lastName) or ""
    org, phone, email, url = map(escape, (org, phone, email, url))

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{lastName};{firstName};;;",
        f"FN:{(firstName + ' ' + lastName).strip()}",
    ]
    if org: lines.append(f"ORG:{org}")
    if phone: lines.append("TEL;TYPE=WORK,VOICE:" + phone)
    if email: lines.append("EMAIL;TYPE=INTERNET,WORK:" + email)
    if url:   lines.append("URL:" + url)

    lines.append("END:VCARD")
    return "\r\n".join(lines)

# ---------- Styled renderer (dots + square finders) ----------

def _isInFinder(row: int, col: int, n: int) -> bool:
    inTL = (0 <= row < 7) and (0 <= col < 7)
    inTR = (0 <= row < 7) and (n - 7 <= col < n)
    inBL = (n - 7 <= row < n) and (0 <= col < 7)
    return inTL or inTR or inBL

def _drawFinderSquares(draw: ImageDraw.ImageDraw, topLeftX: int, topLeftY: int, modulePx: int, color: tuple):
    x, y, m = topLeftX, topLeftY, modulePx
    # Outer ring
    draw.rectangle([x, y, x + 7*m - 1, y + 1*m - 1], fill=color)
    draw.rectangle([x, y + 6*m, x + 7*m - 1, y + 7*m - 1], fill=color)
    draw.rectangle([x, y + 1*m, x + 1*m - 1, y + 6*m - 1], fill=color)
    draw.rectangle([x + 6*m, y + 1*m, x + 7*m - 1, y + 6*m - 1], fill=color)
    # Center 3x3
    draw.rectangle([x + 2*m, y + 2*m, x + 5*m - 1, y + 5*m - 1], fill=color)

def generateStyledQrFixedFill(
    data: str,
    targetPx: int = 250,
    symbolPxGoal: int = 200,
    minModulePx: int = 3,
    requiredQuietModules: int = 4,
    dotScale: float = 0.82,
    colorHex: str = "#000000",
) -> Image.Image:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_L, border=0, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    mat = qr.get_matrix()
    n = len(mat)

    modulePx = max(minModulePx, symbolPxGoal // n)
    while True:
        symbolPxUsed = modulePx * n
        marginPerSide = (targetPx - symbolPxUsed) // 2
        if marginPerSide >= requiredQuietModules * modulePx:
            break
        modulePx -= 1
        if modulePx < minModulePx:
            raise ValueError("targetPx too small for quiet zone; raise targetPx or lower quiet zone.")
    symbolPxUsed = modulePx * n
    marginPerSide = (targetPx - symbolPxUsed) // 2

    img = Image.new("RGBA", (targetPx, targetPx), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = tuple(int(colorHex.strip("#")[i:i+2], 16) for i in (0, 2, 4)) + (255,)

    offsetX, offsetY = marginPerSide, marginPerSide

    # Finders
    for fr, fc in [(0, 0), (0, n - 7), (n - 7, 0)]:
        x = offsetX + fc * modulePx
        y = offsetY + fr * modulePx
        _drawFinderSquares(draw, x, y, modulePx, color)

    # Data modules (round dots)
    radius = (modulePx * dotScale) / 2.0
    for row in range(n):
        for col in range(n):
            if not mat[row][col] or _isInFinder(row, col, n):
                continue
            cx = offsetX + col * modulePx + modulePx / 2.0
            cy = offsetY + row * modulePx + modulePx / 2.0
            bbox = [int(round(cx - radius)), int(round(cy - radius)),
                    int(round(cx + radius)), int(round(cy + radius))]
            draw.ellipse(bbox, fill=color)

    return img

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Styled QR Generator", page_icon="🔳", layout="centered")

st.title("Styled QR Generator (dots + square finders)")
st.caption("Fixed-size symbol with enforced quiet zone. No address fields in vCard.")

with st.sidebar:
    st.header("Rendering options")
    targetPx = st.slider("Target PNG size (px)", 200, 1024, 250, step=10)
    symbolPxGoal = st.slider("Symbol pixel goal (px)", 100, targetPx, 200, step=5)
    minModulePx = st.slider("Minimum module size (px)", 1, 10, 3, step=1)
    requiredQuietModules = st.slider("Quiet zone (modules each side)", 0, 8, 4, step=1)
    dotScale = st.slider("Dot scale per module", 0.5, 1.0, 0.82, step=0.01)
    colorHex = st.color_picker("QR color", "#000000")

tabV, tabL = st.tabs(["vCard", "Link"])

with tabV:
    st.subheader("vCard (VERSION:3.0)")
    cols = st.columns(2)
    firstName = cols[0].text_input("First name", value="")
    lastName = cols[1].text_input("Last name", value="")
    org = st.text_input("Company / Organization", value="")
    phone = st.text_input("Phone (e.g., +1 604 555 1234)", value="")
    email = st.text_input("Work email", value="")
    url = st.text_input("Website (optional)", value="")

    vPreview = st.checkbox("Show vCard text (debug)", value=False)
    vcard = buildVcard(firstName, lastName, org, phone, email, url)
    if vPreview:
        st.code(vcard, language="text")

    if st.button("Generate vCard QR"):
        try:
            img = generateStyledQrFixedFill(
                vcard,
                targetPx=targetPx,
                symbolPxGoal=symbolPxGoal,
                minModulePx=minModulePx,
                requiredQuietModules=requiredQuietModules,
                dotScale=dotScale,
                colorHex=colorHex,
            )
            st.image(img, caption="QR preview", use_container_width=False)

            buf = BytesIO()
            img.save(buf, format="PNG")
            st.download_button(
                label="Download PNG",
                data=buf.getvalue(),
                file_name="vcard-qr.png",
                mime="image/png",
            )
        except Exception as e:
            st.error(str(e))

with tabL:
    st.subheader("Link / URL")
    link = st.text_input("Enter link", value="", help="If missing a scheme, https:// will be prepended.")
    if st.button("Generate Link QR"):
        try:
            ln = link.strip()
            if ln and not (ln.startswith("http://") or ln.startswith("https://")):
                ln = "https://" + ln

            img = generateStyledQrFixedFill(
                ln,
                targetPx=targetPx,
                symbolPxGoal=symbolPxGoal,
                minModulePx=minModulePx,
                requiredQuietModules=requiredQuietModules,
                dotScale=dotScale,
                colorHex=colorHex,
            )
            st.image(img, caption="QR preview", use_container_width=False)

            buf = BytesIO()
            img.save(buf, format="PNG")
            st.download_button(
                label="Download PNG",
                data=buf.getvalue(),
                file_name="link-qr.png",
                mime="image/png",
            )
        except Exception as e:
            st.error(str(e))

st.divider()
with st.expander("Notes"):
    st.markdown(
        "- Quiet zone is enforced in **modules** (multiples of the module pixel size) around the symbol.\n"
        "- If the target image is too small for your chosen quiet zone, you’ll see an error. Increase targetPx or reduce quiet zone.\n"
        "- The dotScale controls round dot diameter within each module (0.82 matches your script default).\n"
        "- Output is PNG with transparent background (RGBA)."
    )
