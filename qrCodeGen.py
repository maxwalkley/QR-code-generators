# app.py
# pip install -r requirements.txt
from io import BytesIO
from pathlib import Path
import math

import streamlit as st
import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from PIL import Image, ImageDraw, ImageOps, ImageFilter

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

def _ec_from_choice(choice: str, logo_present: bool) -> int:
    if choice == "Auto":
        return ERROR_CORRECT_H if logo_present else ERROR_CORRECT_L
    return {
        "L": ERROR_CORRECT_L,
        "M": ERROR_CORRECT_M,
        "Q": ERROR_CORRECT_Q,
        "H": ERROR_CORRECT_H,
    }[choice]

def _rounded_rect(w: int, h: int, r: int, fill=(255, 255, 255, 255)) -> Image.Image:
    """Create a rounded rectangle RGBA image."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, w-1, h-1], radius=r, fill=fill)
    return img

def generateStyledQrFixedFill(
    data: str,
    targetPx: int = 250,
    symbolPxGoal: int = 200,
    minModulePx: int = 3,
    requiredQuietModules: int = 4,
    dotScale: float = 0.82,
    colorHex: str = "#000000",
    # Center image options
    centerImage: Image.Image | None = None,
    centerScale: float = 0.20,          # fraction of total PNG size for logo bitmap
    # Reserve options (draw around the image)
    reserveModules: int | None = None,  # side length of reserved square in MODULES (no data drawn)
    reservePaddingModules: int = 1,     # extra cushion (modules) around the logo area
    drawLogoBackdrop: bool = True,      # draw a white rounded rect under the logo
    backdropCornerRadiusPx: int = 12,
    # Error correction
    errorCorrectionChoice: str = "Auto" # "Auto", "L", "M", "Q", "H"
) -> Image.Image:
    logo_present = centerImage is not None
    ec_level = _ec_from_choice(errorCorrectionChoice, logo_present)

    qr = qrcode.QRCode(error_correction=ec_level, border=0, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    mat = qr.get_matrix()
    n = len(mat)  # number of modules

    # Compute module size to hit symbolPxGoal while honoring quiet zone
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

    # Finder patterns
    for fr, fc in [(0, 0), (0, n - 7), (n - 7, 0)]:
        x = offsetX + fc * modulePx
        y = offsetY + fr * modulePx
        _drawFinderSquares(draw, x, y, modulePx, color)

    # Determine reserved square in MODULE coordinates (centered)
    # If not provided explicitly, infer from centerScale and padding.
    res_modules = 0
    if centerImage is not None:
        # Convert desired logo pixel size to modules (+ padding)
        desired_logo_px = max(1, int(targetPx * centerScale))
        # total reserved pixels = logo + 2*padding_in_px
        pad_px = reservePaddingModules * modulePx
        total_res_px = desired_logo_px + 2 * pad_px
        res_modules = max(0, min(n, math.ceil(total_res_px / modulePx)))

    if reserveModules is not None:
        res_modules = max(res_modules, min(n, int(reserveModules)))  # respect explicit override

    # Center the reserved square
    if res_modules > 0:
        res_start = (n - res_modules) // 2
        res_end = res_start + res_modules - 1
    else:
        res_start = res_end = -1  # no reserve

    # Data dots (skip finders and reserved square)
    radius = (modulePx * dotScale) / 2.0
    for row in range(n):
        for col in range(n):
            if not mat[row][col]:
                continue
            if _isInFinder(row, col, n):
                continue
            if res_modules > 0 and (res_start <= row <= res_end) and (res_start <= col <= res_end):
                # Skip drawing inside reserved region
                continue
            cx = offsetX + col * modulePx + modulePx / 2.0
            cy = offsetY + row * modulePx + modulePx / 2.0
            bbox = [int(round(cx - radius)), int(round(cy - radius)),
                    int(round(cx + radius)), int(round(cy + radius))]
            draw.ellipse(bbox, fill=color)

    # Backdrop + logo (centered)
    if centerImage is not None:
        logo = centerImage.convert("RGBA")
        logo_size = max(1, int(targetPx * centerScale))
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

        # Compute reserved px rect (use the same values as above)
        pad_px = reservePaddingModules * modulePx
        total_res_px = max(logo_size + 2 * pad_px, 0)
        total_res_px = min(total_res_px, targetPx)  # clamp

        res_w = res_h = total_res_px if res_modules > 0 else logo_size
        res_x = (targetPx - res_w) // 2
        res_y = (targetPx - res_h) // 2

        # Optional white rounded rectangle backdrop to separate logo from modules
        if drawLogoBackdrop:
            rr = _rounded_rect(res_w, res_h, backdropCornerRadiusPx, fill=(255, 255, 255, 255))
            img.alpha_composite(rr, (res_x, res_y))

        # Center logo on top
        posX = (targetPx - logo_size) // 2
        posY = (targetPx - logo_size) // 2
        img.alpha_composite(logo, (posX, posY))

    return img

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Styled QR Generator", page_icon="🔳", layout="centered")
st.title("Styled QR Generator (dots + square finders)")
st.caption("Fixed-size symbol with enforced quiet zone. Optional reserved center for logo. No address fields in vCard.")

with st.sidebar:
    st.header("Rendering options")
    targetPx = st.slider("Target PNG size (px)", 200, 1024, 250, step=10)
    symbolPxGoal = st.slider("Symbol pixel goal (px)", 100, targetPx, 200, step=5)
    minModulePx = st.slider("Minimum module size (px)", 1, 10, 3, step=1)
    requiredQuietModules = st.slider("Quiet zone (modules each side)", 0, 8, 4, step=1)
    dotScale = st.slider("Dot scale per module", 0.5, 1.0, 0.82, step=0.01)
    colorHex = st.color_picker("QR color", "#000000")

    st.markdown("---")
    st.subheader("Error correction")
    ec_choice = st.selectbox("Level", ["Auto", "L", "M", "Q", "H"], index=0, help="Auto = H when logo is present, else L.")

    st.markdown("---")
    st.subheader("Center image & reserve")
    uploaded = st.file_uploader("Upload PNG (transparent recommended)", type=["png"])
    centerScale = st.slider("Logo size (fraction of PNG)", 0.05, 0.40, 0.20, step=0.01)
    useReserve = st.checkbox("Reserve centered area (draw around logo)", value=True)
    reserveModules = st.number_input("Reserved square side (modules) [optional override]", min_value=0, max_value=200, value=0, step=1, help="0 = let app infer from logo size + padding. Otherwise forces a module-sized hole.")
    reservePaddingModules = st.slider("Extra padding around logo (modules)", 0, 8, 1, step=1)
    drawBackdrop = st.checkbox("Draw white rounded backdrop under logo", value=False)
    backdropCornerRadiusPx = st.slider("Backdrop corner radius (px)", 0, 40, 12, step=1)

tabV, tabL = st.tabs(["vCard", "Link"])

def buildCenterImage():
    if uploaded is None:
        return None
    try:
        return Image.open(uploaded)
    except Exception:
        st.warning("Could not open uploaded file as an image.")
        return None

def render_and_download(payload: str, filename: str):
    try:
        centerImg = buildCenterImage()
        # If user disabled reserve, set reserveModules to 0 so we don't skip modules.
        res_override = None if (useReserve and reserveModules == 0) else (reserveModules if useReserve else 0)

        img = generateStyledQrFixedFill(
            payload,
            targetPx=targetPx,
            symbolPxGoal=symbolPxGoal,
            minModulePx=minModulePx,
            requiredQuietModules=requiredQuietModules,
            dotScale=dotScale,
            colorHex=colorHex,
            centerImage=centerImg,
            centerScale=centerScale,
            reserveModules=res_override,
            reservePaddingModules=reservePaddingModules if useReserve else 0,
            drawLogoBackdrop=drawBackdrop,
            backdropCornerRadiusPx=backdropCornerRadiusPx,
            errorCorrectionChoice=ec_choice,
        )
        st.image(img, caption="QR preview", use_container_width=False)

        buf = BytesIO()
        img.save(buf, format="PNG")
        st.download_button(
            label="Download PNG",
            data=buf.getvalue(),
            file_name=filename,
            mime="image/png",
        )
    except Exception as e:
        st.error(str(e))

with tabV:
    st.subheader("vCard (VERSION:3.0)")
    cols = st.columns(2)
    firstName = cols[0].text_input("First name", value="")
    lastName = cols[1].text_input("Last name", value="")
    org = st.text_input("Company / Organization", value="")
    phone = st.text_input("Phone (e.g., +1 604 555 1234)", value="")
    email = st.text_input("Work email", value="")
    url = st.text_input("Website", value="")

    vPreview = st.checkbox("Show vCard text (debug)", value=False)
    vcard = buildVcard(firstName, lastName, org, phone, email, url)
    if vPreview:
        st.code(vcard, language="text")

    if st.button("Generate vCard QR"):
        render_and_download(vcard, "vcard-qr.png")

with tabL:
    st.subheader("Link / URL")
    link = st.text_input("Enter link", value="", help="If missing a scheme, https:// will be prepended.")
    if st.button("Generate Link QR"):
        ln = link.strip()
        if ln and not (ln.startswith("http://") or ln.startswith("https://")):
            ln = "https://" + ln
        render_and_download(ln, "link-qr.png")

st.divider()
with st.expander("Notes"):
    st.markdown(
        "- **Reserve mode** skips drawing modules inside a centered square so the QR literally ‘scales around’ your logo.\n"
        "- The reserve size is computed from logo size + padding (in modules). You can override it explicitly.\n"
        "- Using a logo removes data modules; choose higher **error correction** (Auto→H) and keep the **quiet zone** intact.\n"
        "- Transparent PNGs and a white rounded backdrop usually scan best.\n"
        "- Output is PNG with transparent background (RGBA)."
    )
