from flask import Flask, render_template, request, redirect, url_for, flash, g, current_app
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
import os
import datetime
import click
from flask.cli import with_appcontext
from dotenv import load_dotenv
from pymongo import MongoClient # Import MongoClient secara langsung
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session

# Muat variabel lingkungan dari file .env
load_dotenv()

app = Flask(__name__)

# --- Hapus baris ini: os.makedirs(app.instance_path) ---
# Lingkungan Vercel bersifat read-only, jadi tidak bisa membuat direktori di sini.
# Konfigurasi dan data akan diakses melalui variabel lingkungan dan MongoDB Atlas.

# Konfigurasi MongoDB - Sekarang diambil dari variabel lingkungan
mongo_uri = os.environ.get("MONGO_URI")
if not mongo_uri:
    print("PERINGATAN: Variabel lingkungan MONGO_URI tidak ditemukan. Menggunakan URI localhost default.")
    mongo_uri = "mongodb://localhost:27017/slip_gaji_db"

app.config["MONGO_URI"] = mongo_uri
print(f"DEBUG: MONGO_URI diatur ke: {app.config['MONGO_URI']}")

# Konfigurasi SECRET_KEY - Sekarang diambil dari variabel lingkungan
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

if not app.config['SECRET_KEY']:
    raise ValueError("Tidak ada SECRET_KEY yang diatur. Harap atur di file .env atau variabel lingkungan.")
print(f"DEBUG: SECRET_KEY diatur (panjang: {len(app.config['SECRET_KEY'])})")

# --- Inisialisasi PyMongo tanpa mengikatnya ke 'app' secara langsung di tingkat global ---
# Objek 'mongo_instance' ini akan digunakan oleh get_mongo_db() untuk rute web.
mongo_instance = PyMongo()

# Fungsi helper untuk mendapatkan objek database PyMongo yang terhubung
def get_mongo_db():
    # Gunakan g untuk menyimpan objek PyMongo yang sudah diinisialisasi
    # Ini memastikan init_app hanya dipanggil sekali per konteks (request atau CLI command)
    if 'pymongo_db_obj' not in g:
        try:
            # Inisialisasi PyMongo dengan aplikasi yang sedang berjalan
            mongo_instance.init_app(current_app)
            # Coba ping database untuk memastikan koneksi aktif
            mongo_instance.cx.admin.command('ping')
            print("DEBUG: Koneksi MongoDB berhasil dibuat dan diuji (di dalam get_mongo_db untuk web).")
            # Akses database yang benar
            g.pymongo_db_obj = mongo_instance.cx.get_database("slip_gaji_db") # Pastikan nama database yang benar
            print(f"DEBUG: Nama database yang diakses di web: {g.pymongo_db_obj.name}")
        except Exception as e:
            print(f"KESALAHAN: Gagal terhubung ke MongoDB (di dalam get_mongo_db untuk web): {e}")
            print("Harap pastikan server MongoDB Anda berjalan dan MONGO_URI sudah benar.")
            g.pymongo_db_obj = None # Set ke None jika koneksi gagal
    return g.pymongo_db_obj

# Informasi Admin (Sebaiknya diambil dari database pada aplikasi yang lebih kompleks)
ADMINS = {
    'admin': generate_password_hash('ekasaputra09') # Ganti 'passwordadmin' dengan kata sandi yang kuat
}

# Fungsi untuk memeriksa apakah pengguna adalah admin
def is_admin_logged_in():
    return 'admin_logged_in' in session and session['admin_logged_in']

# Dekorator untuk melindungi rute admin
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin_logged_in():
            flash('Anda harus login sebagai admin untuk mengakses halaman ini.', 'danger')
            return redirect(url_for('login_admin'))
        return f(*args, **kwargs)
    return decorated_function

# Rute Login Admin
@app.route('/admin/login', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in ADMINS and check_password_hash(ADMINS[username], password):
            session['admin_logged_in'] = True
            flash('Login admin berhasil!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Login gagal. Username atau password salah.', 'danger')
    return render_template('login_admin.html')

# Rute Logout Admin
@app.route('/admin/logout')
def logout_admin():
    session.pop('admin_logged_in', None)
    flash('Anda telah logout dari admin.', 'info')
    return redirect(url_for('login_admin'))

# Contoh Rute Dashboard Admin (Dilindungi)
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/', defaults={'karyawan_id': None})
@app.route('/slip_gaji/<karyawan_id>')
def slip_gaji(karyawan_id):
    db_obj = get_mongo_db()
    if db_obj is None:
        flash("Aplikasi tidak dapat terhubung ke database. Silakan hubungi administrator atau coba lagi nanti.", 'danger')
        return render_template('error_db.html', message="Koneksi database gagal.")
    
    karyawan_collection = db_obj.karyawan
    absensi_collection = db_obj.absensi
    
    all_karyawan = list(karyawan_collection.find({}))

    selected_karyawan = None
    absensi_gaji = []
    total_gaji = 0

    if not all_karyawan:
        flash("Belum ada data karyawan. Silakan tambahkan karyawan pertama Anda.", 'info')
        return redirect(url_for('add_karyawan'))
    
    if karyawan_id:
        try:
            selected_karyawan = karyawan_collection.find_one({'_id': ObjectId(karyawan_id)})
            if not selected_karyawan:
                flash("Karyawan tidak ditemukan.", 'danger')
                return redirect(url_for('slip_gaji'))
        except Exception:
            flash("ID Karyawan tidak valid.", 'danger')
            return redirect(url_for('slip_gaji'))
    else:
        selected_karyawan = all_karyawan[0]

    if selected_karyawan:
        absensi_gaji = list(absensi_collection.find({'karyawan_id': selected_karyawan['_id']}).sort('tanggal', 1))
        total_gaji = sum(item.get('gaji_harian', 0) for item in absensi_gaji if item.get('gaji_harian') is not None)

    return render_template(
        'slip_gaji.html',
        all_karyawan=all_karyawan,
        karyawan=selected_karyawan,
        absensi_gaji=absensi_gaji,
        total_gaji=total_gaji
    )

# --- Fitur Tambah Karyawan ---
@app.route('/add_karyawan', methods=['GET', 'POST'])
@admin_required
def add_karyawan():
    db_obj = get_mongo_db()
    if db_obj is None:
        flash("Database tidak tersedia.", 'danger')
        return redirect(url_for('slip_gaji'))
    karyawan_collection = db_obj.karyawan
    
    if request.method == 'POST':
        nama = request.form['nama']
        no_rek = request.form['no_rek']
        periode = request.form['periode']

        if not nama or not no_rek or not periode:
            flash('Semua kolom harus diisi!', 'danger')
            return render_template('add_karyawan.html', form_data=request.form)
        
        existing_karyawan = karyawan_collection.find_one({'nama': nama})
        if existing_karyawan:
            flash(f'Karyawan dengan nama "{nama}" sudah ada.', 'danger')
            return render_template('add_karyawan.html', form_data=request.form)

        try:
            new_karyawan_data = {
                'nama': nama,
                'no_rek': no_rek,
                'periode': periode
            }
            result = karyawan_collection.insert_one(new_karyawan_data)
            flash('Karyawan berhasil ditambahkan!', 'success')
            return redirect(url_for('slip_gaji', karyawan_id=str(result.inserted_id)))
        except Exception as e:
            flash(f'Terjadi kesalahan saat menambahkan karyawan: {e}', 'danger')

    return render_template('add_karyawan.html', form_data={})

# --- Fitur Edit Karyawan ---
@app.route('/edit_karyawan/<karyawan_id>', methods=['GET', 'POST'])
@admin_required
def edit_karyawan(karyawan_id):
    db_obj = get_mongo_db()
    if db_obj is None:
        flash("Database tidak tersedia.", 'danger')
        return redirect(url_for('slip_gaji'))
    karyawan_collection = db_obj.karyawan
    
    try:
        karyawan = karyawan_collection.find_one({'_id': ObjectId(karyawan_id)})
        if not karyawan:
            flash("Karyawan tidak ditemukan.", 'danger')
            return redirect(url_for('slip_gaji'))
    except Exception:
        flash("ID Karyawan tidak valid.", 'danger')
        return redirect(url_for('slip_gaji'))

    if request.method == 'POST':
        nama = request.form['nama']
        no_rek = request.form['no_rek']
        periode = request.form['periode']

        if not nama or not no_rek or not periode:
            flash('Semua kolom harus diisi!', 'danger')
            return render_template('edit_karyawan.html', karyawan=karyawan)
        
        existing_karyawan = karyawan_collection.find_one({
            'nama': nama,
            '_id': {'$ne': ObjectId(karyawan_id)}
        })
        if existing_karyawan:
            flash(f'Karyawan dengan nama "{nama}" sudah ada.', 'danger')
            return render_template('edit_karyawan.html', karyawan=karyawan)

        try:
            karyawan_collection.update_one(
                {'_id': ObjectId(karyawan_id)},
                {'$set': {'nama': nama, 'no_rek': no_rek, 'periode': periode}}
            )
            flash('Data karyawan berhasil diperbarui!', 'success')
            return redirect(url_for('slip_gaji', karyawan_id=karyawan_id))
        except Exception as e:
            flash(f'Terjadi kesalahan saat memperbarui karyawan: {e}', 'danger')

    return render_template('edit_karyawan.html', karyawan=karyawan)


# --- Fitur Tambah Absensi ---
@app.route('/add_absensi/<karyawan_id>', methods=['GET', 'POST'])
@admin_required
def add_absensi(karyawan_id):
    db_obj = get_mongo_db()
    if db_obj is None:
        flash("Database tidak tersedia.", 'danger')
        return redirect(url_for('slip_gaji'))
    karyawan_collection = db_obj.karyawan
    absensi_collection = db_obj.absensi

    try:
        karyawan = karyawan_collection.find_one({'_id': ObjectId(karyawan_id)})
        if not karyawan:
            flash("Karyawan tidak ditemukan.", 'danger')
            return redirect(url_for('slip_gaji'))
    except Exception:
        flash("ID Karyawan tidak valid.", 'danger')
        return redirect(url_for('slip_gaji'))

    if request.method == 'POST':
        tanggal_str = request.form['tanggal']
        status = request.form['status']
        gaji_harian_str = request.form.get('gaji_harian')

        try:
            tanggal = datetime.datetime.strptime(tanggal_str, '%Y-%m-%d').date()
            tanggal_dt = datetime.datetime.combine(tanggal, datetime.time())
            gaji_harian = int(gaji_harian_str) if gaji_harian_str else None

            existing_record = absensi_collection.find_one({'karyawan_id': ObjectId(karyawan_id), 'tanggal': tanggal_dt})
            if existing_record:
                flash(f'Absensi untuk tanggal {tanggal_str} sudah ada.', 'danger')
                return redirect(url_for('add_absensi', karyawan_id=karyawan_id))

            new_absensi_data = {
                'karyawan_id': ObjectId(karyawan_id),
                'tanggal': tanggal_dt,
                'status': status,
                'gaji_harian': gaji_harian
            }
            absensi_collection.insert_one(new_absensi_data)
            flash('Absensi berhasil ditambahkan!', 'success')
            return redirect(url_for('slip_gaji', karyawan_id=karyawan_id))
        except ValueError:
            flash('Format tanggal atau gaji harian tidak valid.', 'danger')
        except Exception as e:
            flash(f'Terjadi kesalahan: {e}', 'danger')

    return render_template('add_absensi.html', karyawan=karyawan)

# --- Fitur Edit Absensi ---
@app.route('/edit_absensi/<absensi_id>', methods=['GET', 'POST'])
@admin_required
def edit_absensi(absensi_id):
    db_obj = get_mongo_db()
    if db_obj is None:
        flash("Database tidak tersedia.", 'danger')
        return redirect(url_for('slip_gaji'))
    karyawan_collection = db_obj.karyawan
    absensi_collection = db_obj.absensi

    try:
        absensi = absensi_collection.find_one({'_id': ObjectId(absensi_id)})
        if not absensi:
            flash("Absensi tidak ditemukan.", 'danger')
            return redirect(url_for('slip_gaji'))
        karyawan = karyawan_collection.find_one({'_id': absensi['karyawan_id']})
        if not karyawan:
            flash("Karyawan terkait absensi tidak ditemukan.", 'danger')
            return redirect(url_for('slip_gaji'))
    except Exception:
        flash("ID Absensi tidak valid.", 'danger')
        return redirect(url_for('slip_gaji'))

    if request.method == 'POST':
        tanggal_str = request.form['tanggal']
        status = request.form['status']
        gaji_harian_str = request.form.get('gaji_harian')

        try:
            tanggal = datetime.datetime.strptime(tanggal_str, '%Y-%m-%d').date()
            tanggal_dt = datetime.datetime.combine(tanggal, datetime.time())
            gaji_harian = int(gaji_harian_str) if gaji_harian_str else None

            existing_record = absensi_collection.find_one({
                'karyawan_id': karyawan['_id'],
                'tanggal': tanggal_dt,
                '_id': {'$ne': ObjectId(absensi_id)}
            })
            if existing_record:
                flash(f'Tanggal {tanggal_str} sudah digunakan pada catatan absensi lain untuk karyawan ini.', 'danger')
                return redirect(url_for('edit_absensi', absensi_id=absensi_id))

            absensi_collection.update_one(
                {'_id': ObjectId(absensi_id)},
                {'$set': {
                    'tanggal': tanggal_dt,
                    'status': status,
                    'gaji_harian': gaji_harian
                }}
            )
            flash('Absensi berhasil diperbarui!', 'success')
            return redirect(url_for('slip_gaji', karyawan_id=str(karyawan['_id'])))
        except ValueError:
            flash('Format tanggal atau gaji harian tidak valid.', 'danger')
        except Exception as e:
            flash(f'Terjadi kesalahan: {e}', 'danger')

    return render_template('edit_absensi.html', absensi=absensi, karyawan=karyawan)

# --- Fitur Hapus Absensi ---
@app.route('/delete_absensi/<absensi_id>', methods=['POST'])
@admin_required
def delete_absensi(absensi_id):
    db_obj = get_mongo_db()
    if db_obj is None:
        flash("Database tidak tersedia.", 'danger')
        return redirect(url_for('slip_gaji'))
    absensi_collection = db_obj.absensi

    try:
        absensi = absensi_collection.find_one({'_id': ObjectId(absensi_id)})
        if not absensi:
            flash("Absensi tidak ditemukan.", 'danger')
            return redirect(url_for('slip_gaji'))
        
        karyawan_id = str(absensi['karyawan_id'])
        
        absensi_collection.delete_one({'_id': ObjectId(absensi_id)})
        flash('Absensi berhasil dihapus!', 'success')
    except Exception as e:
        flash(f'Terjadi kesalahan saat menghapus absensi: {e}', 'danger')
    return redirect(url_for('slip_gaji', karyawan_id=karyawan_id))

# --- Perintah CLI Kustom untuk Inisialisasi Database ---
@app.cli.command('init-db')
@with_appcontext
def init_db_command():
    """Bersihkan data yang ada dan buat koleksi baru, lalu isi dengan data contoh."""
    # Menggunakan MongoClient secara langsung untuk perintah CLI
    # Ini akan memastikan koneksi langsung tanpa perantara Flask-PyMongo
    try:
        # Menggunakan 'with' statement untuk memastikan klien ditutup dengan benar
        with MongoClient(app.config["MONGO_URI"]) as client:
            # Coba ping database untuk memastikan koneksi aktif
            client.admin.command('ping')
            
            # Dapatkan objek database yang benar
            # Karena URI Anda tidak menentukan database, kita secara eksplisit menentukannya di sini.
            db_obj = client.get_database("slip_gaji_db") # Ganti dengan nama database Anda yang sebenarnya
            
            click.echo("DEBUG: Koneksi MongoDB berhasil dibuat dan diuji (melalui MongoClient langsung).")
            click.echo(f"DEBUG: Nama database yang diakses di CLI: {db_obj.name}")

            # Tambahkan debug print untuk melacak nilai db_obj sebelum operasi
            click.echo(f"DEBUG: db_obj sebelum operasi di init_db_command: {db_obj}")
            click.echo(f"DEBUG: Tipe db_obj: {type(db_obj)}")
            click.echo(f"DEBUG: db_obj is None: {db_obj is None}")

            if db_obj is None: # Ini seharusnya tidak terjadi jika ping berhasil
                click.echo("KESALAHAN: Koneksi MongoDB tidak terjalin. Objek database adalah None.")
                return

            karyawan_collection = db_obj.karyawan
            absensi_collection = db_obj.absensi

            click.echo('Membersihkan data yang ada...')
            karyawan_collection.delete_many({})
            absensi_collection.delete_many({})
            click.echo('Koleksi dibersihkan.')

            if karyawan_collection.count_documents({}) == 0:
                click.echo("Menambahkan contoh data ke database...")
                
                eka_data = {
                    'nama': 'Eka Saputra',
                    'no_rek': '7611053294 BCA a/n Rusdiyana',
                    'periode': '01-16 Mei 2025'
                }
                result_eka = karyawan_collection.insert_one(eka_data)
                eka_id = result_eka.inserted_id

                absensi_data = [
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 1), 'status': 'CUTI HARI BURUH', 'gaji_harian': None},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 2), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 3), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 4), 'status': 'OFF', 'gaji_harian': None},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 5), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 6), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 7), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 8), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 9), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 10), 'status': 'OFF', 'gaji_harian': None},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 11), 'status': 'OFF', 'gaji_harian': None},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 12), 'status': 'CUTI WAISAK', 'gaji_harian': None},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 13), 'status': 'CUTI WAISAK', 'gaji_harian': None},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 14), 'status': 'Hadir', 'gaji_harian': 70000},
                    {'karyawan_id': eka_id, 'tanggal': datetime.datetime(2025, 5, 15), 'status': 'Hadir', 'gaji_harian': 70000},
                ]
                absensi_collection.insert_many(absensi_data)
                click.echo("Contoh data berhasil ditambahkan.")
            else:
                click.echo("Data karyawan sudah ada, tidak menambahkan contoh data.")

    except Exception as e:
        click.echo(f"KESALAHAN: Terjadi kesalahan fatal saat inisialisasi atau operasi database: {e}")
        click.echo("Koneksi MongoDB tidak terjalin. Tidak dapat menginisialisasi database.")
        return
