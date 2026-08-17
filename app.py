from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
import os
import secrets
from datetime import datetime

# Render (ve diğer hosting servisleri) veritabanı adresini bu ortam değişkeniyle verir.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Yönetim paneline (admin) girmek için kullanılan şifre. Render'da bunu
# "Environment" ayarlarından ADMIN_SIFRE olarak kendi belirlediğiniz güçlü
# bir şifreyle değiştirmeniz önerilir. Ayarlanmazsa aşağıdaki varsayılan kullanılır.
ADMIN_SIFRE = os.environ.get("ADMIN_SIFRE", "koyumuz2026")

app = Flask(__name__)
# Mobil uygulamanın (farklı bir adresten/porttan) bu API'ye erişebilmesi için gerekli.
CORS(app)


def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL ortam değişkeni ayarlı değil. "
            "Lütfen Postgres bağlantı adresinizi DATABASE_URL olarak ayarlayın."
        )
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS duyurular (
            id SERIAL PRIMARY KEY,
            baslik TEXT NOT NULL,
            icerik TEXT NOT NULL,
            tarih TEXT NOT NULL,
            onemli INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS etkinlikler (
            id SERIAL PRIMARY KEY,
            baslik TEXT NOT NULL,
            aciklama TEXT NOT NULL,
            tarih TEXT NOT NULL,
            yer TEXT
        )
        """
    )

    # ---- Üyelik sistemi ----
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id SERIAL PRIMARY KEY,
            ad_soyad TEXT NOT NULL,
            email TEXT,
            telefon TEXT,
            sifre_hash TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'bekliyor',
            token TEXT,
            olusturma_tarihi TEXT
        )
        """
    )

    # ---- Köy fotoğrafları albümü ----
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fotograflar (
            id SERIAL PRIMARY KEY,
            baslik TEXT,
            aciklama TEXT,
            resim TEXT NOT NULL,
            tarih TEXT NOT NULL
        )
        """
    )

    # ---- Rahmetliler ve yaşlılar anı bölümü ----
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS kisiler (
            id SERIAL PRIMARY KEY,
            ad_soyad TEXT NOT NULL,
            tur TEXT NOT NULL,
            dogum_yili TEXT,
            vefat_yili TEXT,
            aciklama TEXT,
            resim TEXT
        )
        """
    )

    # ---- Köy derneği: destekçiler ----
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS destekciler (
            id SERIAL PRIMARY KEY,
            ad_soyad TEXT NOT NULL,
            aciklama TEXT,
            tarih TEXT NOT NULL
        )
        """
    )

    # ---- Köy derneği: harcamalar ----
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS harcamalar (
            id SERIAL PRIMARY KEY,
            baslik TEXT NOT NULL,
            aciklama TEXT,
            tutar NUMERIC NOT NULL DEFAULT 0,
            tarih TEXT NOT NULL
        )
        """
    )

    # ---- Videolar (YouTube linkleri) ----
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS videolar (
            id SERIAL PRIMARY KEY,
            baslik TEXT NOT NULL,
            aciklama TEXT,
            url TEXT NOT NULL,
            tarih TEXT NOT NULL
        )
        """
    )

    # Ornek veri (ilk kurulumda bos gorunmesin diye)
    cur.execute("SELECT COUNT(*) AS c FROM duyurular")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO duyurular (baslik, icerik, tarih, onemli) VALUES (%s, %s, %s, %s)",
            ("Hoş geldiniz", "Köy uygulaması yayında. Duyuru ve etkinlikleri buradan takip edebilirsiniz.", datetime.now().strftime("%Y-%m-%d"), 1),
        )
    cur.execute("SELECT COUNT(*) AS c FROM etkinlikler")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO etkinlikler (baslik, aciklama, tarih, yer) VALUES (%s, %s, %s, %s)",
            ("Köy Meclisi Toplantısı", "Yıllık genel değerlendirme toplantısı.", datetime.now().strftime("%Y-%m-%d"), "Köy Kahvehanesi"),
        )

    conn.commit()
    cur.close()
    conn.close()


# ---------- Yardımcılar: yetkilendirme ----------

def gecerli_uye_mi(token):
    """Verilen token'a sahip, onaylanmış bir üye var mı kontrol eder. Varsa üyeyi döner."""
    if not token:
        return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM kullanicilar WHERE token=%s AND durum='onaylandi'", (token,))
    uye = cur.fetchone()
    cur.close()
    conn.close()
    return uye


def uye_gerekli(f):
    from functools import wraps

    @wraps(f)
    def sarmalayici(*args, **kwargs):
        token = request.headers.get("X-Auth-Token")
        uye = gecerli_uye_mi(token)
        if not uye:
            return jsonify({"hata": "Giriş yapmanız gerekiyor."}), 401
        request.uye = uye
        return f(*args, **kwargs)

    return sarmalayici


def admin_mi():
    sifre = request.headers.get("X-Admin-Sifre")
    return bool(sifre) and sifre == ADMIN_SIFRE


def admin_gerekli(f):
    from functools import wraps

    @wraps(f)
    def sarmalayici(*args, **kwargs):
        if not admin_mi():
            return jsonify({"hata": "Yönetici girişi gerekiyor."}), 401
        return f(*args, **kwargs)

    return sarmalayici


def erisim_gerekli(f):
    """İçerik görüntüleme uç noktaları için: ya onaylanmış bir üye tokenı,
    ya da yönetici şifresi yeterlidir (yönetim paneli de aynı listeleri kullanır)."""
    from functools import wraps

    @wraps(f)
    def sarmalayici(*args, **kwargs):
        if admin_mi():
            request.uye = None
            return f(*args, **kwargs)
        token = request.headers.get("X-Auth-Token")
        uye = gecerli_uye_mi(token)
        if not uye:
            return jsonify({"hata": "Giriş yapmanız gerekiyor."}), 401
        request.uye = uye
        return f(*args, **kwargs)

    return sarmalayici


# ---------- Sayfalar ----------

@app.route("/")
def mobil():
    return render_template("mobil.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/saglik")
def saglik():
    return jsonify({"durum": "ok"})


# ---------- API: Üyelik / Giriş ----------

@app.route("/api/auth/kayit", methods=["POST"])
def uye_kayit():
    data = request.get_json(force=True)
    ad_soyad = (data.get("ad_soyad") or "").strip()
    email = (data.get("email") or "").strip()
    telefon = (data.get("telefon") or "").strip()
    sifre = data.get("sifre") or ""

    if not ad_soyad or not sifre or (not email and not telefon):
        return jsonify({"hata": "Ad soyad, şifre ve en az bir iletişim bilgisi (e-posta veya telefon) gereklidir."}), 400
    if len(sifre) < 4:
        return jsonify({"hata": "Şifre en az 4 karakter olmalıdır."}), 400

    conn = get_db()
    cur = conn.cursor()
    if email:
        cur.execute("SELECT id FROM kullanicilar WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"hata": "Bu e-posta ile zaten bir üyelik var."}), 400
    if telefon:
        cur.execute("SELECT id FROM kullanicilar WHERE telefon=%s", (telefon,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"hata": "Bu telefon ile zaten bir üyelik var."}), 400

    sifre_hash = generate_password_hash(sifre)
    cur.execute(
        "INSERT INTO kullanicilar (ad_soyad, email, telefon, sifre_hash, durum, olusturma_tarihi) VALUES (%s, %s, %s, %s, 'bekliyor', %s) RETURNING id",
        (ad_soyad, email or None, telefon or None, sifre_hash, datetime.now().strftime("%Y-%m-%d")),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id, "mesaj": "Üyelik talebiniz alındı. Yönetici onayından sonra giriş yapabilirsiniz."}), 201


@app.route("/api/auth/giris", methods=["POST"])
def uye_giris():
    data = request.get_json(force=True)
    kimlik = (data.get("kimlik") or "").strip()  # email veya telefon
    sifre = data.get("sifre") or ""

    if not kimlik or not sifre:
        return jsonify({"hata": "E-posta/telefon ve şifre gereklidir."}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM kullanicilar WHERE email=%s OR telefon=%s", (kimlik, kimlik))
    uye = cur.fetchone()

    if not uye or not check_password_hash(uye["sifre_hash"], sifre):
        cur.close()
        conn.close()
        return jsonify({"hata": "Bilgiler hatalı."}), 401

    if uye["durum"] == "bekliyor":
        cur.close()
        conn.close()
        return jsonify({"hata": "Üyeliğiniz henüz yönetici tarafından onaylanmadı."}), 403
    if uye["durum"] == "reddedildi":
        cur.close()
        conn.close()
        return jsonify({"hata": "Üyelik talebiniz reddedildi."}), 403

    token = secrets.token_hex(24)
    cur.execute("UPDATE kullanicilar SET token=%s WHERE id=%s", (token, uye["id"]))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"token": token, "ad_soyad": uye["ad_soyad"]})


@app.route("/api/auth/ben", methods=["GET"])
@uye_gerekli
def uye_ben():
    return jsonify({"ad_soyad": request.uye["ad_soyad"], "email": request.uye["email"], "telefon": request.uye["telefon"]})


# ---------- API: Admin - Üye onayları ----------

@app.route("/api/admin/giris", methods=["POST"])
def admin_giris():
    data = request.get_json(force=True)
    if (data.get("sifre") or "") == ADMIN_SIFRE:
        return jsonify({"ok": True})
    return jsonify({"hata": "Şifre hatalı."}), 401


@app.route("/api/admin/uyeler", methods=["GET"])
@admin_gerekli
def admin_uyeler():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, ad_soyad, email, telefon, durum, olusturma_tarihi FROM kullanicilar ORDER BY (durum='bekliyor') DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/uyeler/<int:uye_id>/onayla", methods=["POST"])
@admin_gerekli
def admin_uye_onayla(uye_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE kullanicilar SET durum='onaylandi' WHERE id=%s", (uye_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/uyeler/<int:uye_id>/reddet", methods=["POST"])
@admin_gerekli
def admin_uye_reddet(uye_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE kullanicilar SET durum='reddedildi' WHERE id=%s", (uye_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/uyeler/<int:uye_id>", methods=["DELETE"])
@admin_gerekli
def admin_uye_sil(uye_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM kullanicilar WHERE id=%s", (uye_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Duyurular (üyelere açık) ----------

@app.route("/api/duyurular", methods=["GET"])
@erisim_gerekli
def duyurular_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM duyurular ORDER BY tarih DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/duyurular", methods=["POST"])
@admin_gerekli
def duyuru_ekle():
    data = request.get_json(force=True)
    baslik = (data.get("baslik") or "").strip()
    icerik = (data.get("icerik") or "").strip()
    tarih = data.get("tarih") or datetime.now().strftime("%Y-%m-%d")
    onemli = 1 if data.get("onemli") else 0
    if not baslik or not icerik:
        return jsonify({"hata": "Başlık ve içerik zorunludur."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO duyurular (baslik, icerik, tarih, onemli) VALUES (%s, %s, %s, %s) RETURNING id",
        (baslik, icerik, tarih, onemli),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/duyurular/<int:duyuru_id>", methods=["PUT"])
@admin_gerekli
def duyuru_guncelle(duyuru_id):
    data = request.get_json(force=True)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE duyurular SET baslik=%s, icerik=%s, tarih=%s, onemli=%s WHERE id=%s",
        (
            (data.get("baslik") or "").strip(),
            (data.get("icerik") or "").strip(),
            data.get("tarih") or datetime.now().strftime("%Y-%m-%d"),
            1 if data.get("onemli") else 0,
            duyuru_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/duyurular/<int:duyuru_id>", methods=["DELETE"])
@admin_gerekli
def duyuru_sil(duyuru_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM duyurular WHERE id=%s", (duyuru_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Etkinlikler (üyelere açık) ----------

@app.route("/api/etkinlikler", methods=["GET"])
@erisim_gerekli
def etkinlikler_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM etkinlikler ORDER BY tarih ASC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/etkinlikler", methods=["POST"])
@admin_gerekli
def etkinlik_ekle():
    data = request.get_json(force=True)
    baslik = (data.get("baslik") or "").strip()
    aciklama = (data.get("aciklama") or "").strip()
    tarih = data.get("tarih") or datetime.now().strftime("%Y-%m-%d")
    yer = (data.get("yer") or "").strip()
    if not baslik or not aciklama:
        return jsonify({"hata": "Başlık ve açıklama zorunludur."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO etkinlikler (baslik, aciklama, tarih, yer) VALUES (%s, %s, %s, %s) RETURNING id",
        (baslik, aciklama, tarih, yer),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/etkinlikler/<int:etkinlik_id>", methods=["PUT"])
@admin_gerekli
def etkinlik_guncelle(etkinlik_id):
    data = request.get_json(force=True)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE etkinlikler SET baslik=%s, aciklama=%s, tarih=%s, yer=%s WHERE id=%s",
        (
            (data.get("baslik") or "").strip(),
            (data.get("aciklama") or "").strip(),
            data.get("tarih") or datetime.now().strftime("%Y-%m-%d"),
            (data.get("yer") or "").strip(),
            etkinlik_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/etkinlikler/<int:etkinlik_id>", methods=["DELETE"])
@admin_gerekli
def etkinlik_sil(etkinlik_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM etkinlikler WHERE id=%s", (etkinlik_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Köy fotoğrafları albümü (üyelere açık) ----------

@app.route("/api/fotograflar", methods=["GET"])
@erisim_gerekli
def fotograflar_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fotograflar ORDER BY tarih DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/fotograflar", methods=["POST"])
@admin_gerekli
def fotograf_ekle():
    data = request.get_json(force=True)
    resim = data.get("resim") or ""
    if not resim:
        return jsonify({"hata": "Fotoğraf gereklidir."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO fotograflar (baslik, aciklama, resim, tarih) VALUES (%s, %s, %s, %s) RETURNING id",
        ((data.get("baslik") or "").strip(), (data.get("aciklama") or "").strip(), resim, data.get("tarih") or datetime.now().strftime("%Y-%m-%d")),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/fotograflar/<int:foto_id>", methods=["DELETE"])
@admin_gerekli
def fotograf_sil(foto_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM fotograflar WHERE id=%s", (foto_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Rahmetliler ve yaşlılar anı bölümü (üyelere açık) ----------

@app.route("/api/kisiler", methods=["GET"])
@erisim_gerekli
def kisiler_listele():
    tur = request.args.get("tur")
    conn = get_db()
    cur = conn.cursor()
    if tur in ("rahmetli", "yasli"):
        cur.execute("SELECT * FROM kisiler WHERE tur=%s ORDER BY id DESC", (tur,))
    else:
        cur.execute("SELECT * FROM kisiler ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/kisiler", methods=["POST"])
@admin_gerekli
def kisi_ekle():
    data = request.get_json(force=True)
    ad_soyad = (data.get("ad_soyad") or "").strip()
    tur = data.get("tur")
    if not ad_soyad or tur not in ("rahmetli", "yasli"):
        return jsonify({"hata": "Ad soyad ve tür (rahmetli/yasli) zorunludur."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO kisiler (ad_soyad, tur, dogum_yili, vefat_yili, aciklama, resim) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            ad_soyad,
            tur,
            (data.get("dogum_yili") or "").strip(),
            (data.get("vefat_yili") or "").strip(),
            (data.get("aciklama") or "").strip(),
            data.get("resim") or None,
        ),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/kisiler/<int:kisi_id>", methods=["PUT"])
@admin_gerekli
def kisi_guncelle(kisi_id):
    data = request.get_json(force=True)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE kisiler SET ad_soyad=%s, tur=%s, dogum_yili=%s, vefat_yili=%s, aciklama=%s, resim=%s WHERE id=%s",
        (
            (data.get("ad_soyad") or "").strip(),
            data.get("tur"),
            (data.get("dogum_yili") or "").strip(),
            (data.get("vefat_yili") or "").strip(),
            (data.get("aciklama") or "").strip(),
            data.get("resim") or None,
            kisi_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/kisiler/<int:kisi_id>", methods=["DELETE"])
@admin_gerekli
def kisi_sil(kisi_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM kisiler WHERE id=%s", (kisi_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Köy derneği - Destekçiler (üyelere açık) ----------

@app.route("/api/destekciler", methods=["GET"])
@erisim_gerekli
def destekciler_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM destekciler ORDER BY tarih DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/destekciler", methods=["POST"])
@admin_gerekli
def destekci_ekle():
    data = request.get_json(force=True)
    ad_soyad = (data.get("ad_soyad") or "").strip()
    if not ad_soyad:
        return jsonify({"hata": "Ad soyad zorunludur."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO destekciler (ad_soyad, aciklama, tarih) VALUES (%s, %s, %s) RETURNING id",
        (ad_soyad, (data.get("aciklama") or "").strip(), data.get("tarih") or datetime.now().strftime("%Y-%m-%d")),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/destekciler/<int:destekci_id>", methods=["DELETE"])
@admin_gerekli
def destekci_sil(destekci_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM destekciler WHERE id=%s", (destekci_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Köy derneği - Harcamalar (üyelere açık) ----------

@app.route("/api/harcamalar", methods=["GET"])
@erisim_gerekli
def harcamalar_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM harcamalar ORDER BY tarih DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/harcamalar", methods=["POST"])
@admin_gerekli
def harcama_ekle():
    data = request.get_json(force=True)
    baslik = (data.get("baslik") or "").strip()
    try:
        tutar = float(data.get("tutar") or 0)
    except (TypeError, ValueError):
        tutar = 0
    if not baslik:
        return jsonify({"hata": "Başlık zorunludur."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO harcamalar (baslik, aciklama, tutar, tarih) VALUES (%s, %s, %s, %s) RETURNING id",
        (baslik, (data.get("aciklama") or "").strip(), tutar, data.get("tarih") or datetime.now().strftime("%Y-%m-%d")),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/harcamalar/<int:harcama_id>", methods=["DELETE"])
@admin_gerekli
def harcama_sil(harcama_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM harcamalar WHERE id=%s", (harcama_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Videolar (üyelere açık) ----------

@app.route("/api/videolar", methods=["GET"])
@erisim_gerekli
def videolar_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM videolar ORDER BY tarih DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/videolar", methods=["POST"])
@admin_gerekli
def video_ekle():
    data = request.get_json(force=True)
    baslik = (data.get("baslik") or "").strip()
    url = (data.get("url") or "").strip()
    if not baslik or not url:
        return jsonify({"hata": "Başlık ve video linki zorunludur."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO videolar (baslik, aciklama, url, tarih) VALUES (%s, %s, %s, %s) RETURNING id",
        (baslik, (data.get("aciklama") or "").strip(), url, data.get("tarih") or datetime.now().strftime("%Y-%m-%d")),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201


@app.route("/api/videolar/<int:video_id>", methods=["DELETE"])
@admin_gerekli
def video_sil(video_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM videolar WHERE id=%s", (video_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# Render gibi servislerde uygulama her başladığında tablo var mı diye kontrol edilir.
try:
    init_db()
except Exception as _e:
    print(f"Not: veritabanı henüz hazırlanamadı ({_e}). DATABASE_URL ayarlandığından emin olun.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
