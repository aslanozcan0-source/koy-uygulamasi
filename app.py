from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import os
from datetime import datetime

# Render (ve diğer hosting servisleri) veritabanı adresini bu ortam değişkeniyle verir.
# Yerelde denerken de bunu kendi bilgisayarınızda kurduğunuz bir Postgres'e
# veya Render'ın size verdiği "External Database URL" adresine ayarlayabilirsiniz.
DATABASE_URL = os.environ.get("DATABASE_URL")

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


# ---------- Sayfalar ----------

@app.route("/")
def mobil():
    return render_template("mobil.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/saglik")
def saglik():
    # Render gibi servislerin uygulamanın ayakta olduğunu kontrol etmesi için basit bir uç nokta.
    return jsonify({"durum": "ok"})


# ---------- API: Duyurular ----------

@app.route("/api/duyurular", methods=["GET"])
def duyurular_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM duyurular ORDER BY tarih DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/duyurular", methods=["POST"])
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
def duyuru_sil(duyuru_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM duyurular WHERE id=%s", (duyuru_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# ---------- API: Etkinlikler ----------

@app.route("/api/etkinlikler", methods=["GET"])
def etkinlikler_listele():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM etkinlikler ORDER BY tarih ASC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/etkinlikler", methods=["POST"])
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
def etkinlik_sil(etkinlik_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM etkinlikler WHERE id=%s", (etkinlik_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


# Render gibi servislerde uygulama her başladığında tablo var mı diye kontrol edilir.
try:
    init_db()
except Exception as _e:
    # DATABASE_URL henüz ayarlanmadıysa (örn. ilk yerel kurulum) burada sessizce geçiyoruz;
    # /api/... uç noktalarına istek geldiğinde anlaşılır bir hata mesajı dönecek.
    print(f"Not: veritabanı henüz hazırlanamadı ({_e}). DATABASE_URL ayarlandığından emin olun.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)

# Köyümüz — Duyuru ve Etkinlik Uygulaması (Sunucu + Yönetim Paneli)

Bu klasör iki şeyi içerir:

- **Sunucu (backend)** — verileri saklayan ve mobil uygulamaya/web sayfasına ileten program.
- **Yönetim paneli (`/admin`)** — sizin bilgisayardan duyuru/etkinlik ekleyip düzenleyeceğiniz sayfa.

Veriler artık bir **PostgreSQL veritabanında** tutuluyor (önceki SQLite dosyası yerine), çünkü Render'ın ücretsiz planında dosyalar sunucu her yeniden başladığında siliniyor; veritabanı bu sorunu yaşamıyor.

## Render'da ücretsiz olarak yayına alma

1. [render.com](https://render.com) hesabınıza giriş yapın.
2. Bu klasördeki tüm dosyaları bir **GitHub** deposuna (repository) yükleyin:
   - GitHub hesabınız yoksa [github.com](https://github.com) üzerinden ücretsiz açabilirsiniz.
   - Yeni bir "repository" oluşturun (örn. adı: `koy-uygulamasi`), ardından GitHub'ın web sayfasındaki "Add file → Upload files" seçeneğiyle bu klasördeki dosyaları sürükleyip bırakabilirsiniz — komut satırına gerek yok.
3. Render'a dönün: **New +** → **Blueprint**.
4. Az önce oluşturduğunuz GitHub deposunu seçin. Render, klasördeki `render.yaml` dosyasını otomatik olarak bulacak ve size hem veritabanını hem sunucuyu (`koyumuz-db` ve `koyumuz-api`) birlikte oluşturmayı önerecek.
5. **Apply / Create** butonuna basın. Birkaç dakika içinde:
   - Veritabanınız hazır olur,
   - Sunucunuz size `https://koyumuz-api.onrender.com` gibi bir adres verir.
6. Bu adresi tarayıcınızda açtığınızda köylülerin göreceği sayfa (`/`), `/admin` eklediğinizde ise yönetim paneli açılır.

## Önemli: ücretsiz veritabanı 30 günde bir yenilenmeli

Render'ın ücretsiz Postgres veritabanı, oluşturulduktan **30 gün sonra süresi doluyor** (14 günlük ek bir süre daha veriyor, sonra veriler siliniyor). Bu süre dolmadan önce Render size e-posta ile hatırlatma gönderir. O noktada iki seçeneğiniz olur:
- Ücretli plana geçmek (küçük bir aylık ücret karşılığında veritabanı kalıcı hale gelir), veya
- Yeni bir ücretsiz veritabanı oluşturup verileri (duyuru/etkinlik listesini) elle yeniden girmek.

Uygulama büyüyüp köylüler gerçekten kullanmaya başladığında, verilerinizi kaybetmemek için ücretli plana geçmenizi öneririm — ama şimdilik denemek için ücretsiz plan gayet uygun.

## Mobil uygulamayı bu sunucuya bağlama

Render'dan aldığınız adresi (`https://koyumuz-api.onrender.com` gibi), `koy-mobil-app` klasöründeki `config.js` dosyasındaki `API_BASE_URL` değeriyle değiştirin. Böylece mobil uygulama artık gerçek, herkesin erişebildiği verileri gösterir.

## Bilgisayarınızda deneme (opsiyonel)

Yayına almadan önce kendi bilgisayarınızda denemek isterseniz, bir Postgres veritabanına ihtiyacınız var. En kolayı, Render'da veritabanını oluşturduktan sonra onun "External Database URL" adresini kopyalayıp şu şekilde kullanmaktır:

```
export DATABASE_URL="Render'dan kopyaladığınız adres"
pip install -r requirements.txt
python app.py
```

Sonra tarayıcıda:
- Köylüler için: http://localhost:5050/
- Yönetim paneli için: http://localhost:5050/admin

## Dosya yapısı

```
koy-uygulamasi/
├── app.py              → Sunucu ve veritabanı işlemleri (Python/Flask)
├── requirements.txt     → Gerekli kütüphane listesi
├── render.yaml           → Render'a tek tıkla kurulum için "tarif" dosyası
├── Procfile               → Render'a uygulamayı nasıl başlatacağını söyler
└── templates/
    ├── mobil.html          → Köylülerin gördüğü sayfa
    └── admin.html          → Yönetim paneli sayfası
```

web: gunicorn app:app

databases:
  - name: koyumuz-db
    plan: free

services:
  - type: web
    name: koyumuz-api
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: koyumuz-db
          property: connectionString

Flask>=2.3
Flask-Cors>=4.0
psycopg2-binary>=2.9
gunicorn>=21.0
