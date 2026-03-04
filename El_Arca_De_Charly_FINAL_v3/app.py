import os, json, io, csv, platform, datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, render_template, flash, send_file, abort, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, func, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, scoped_session
from sqlalchemy.orm import joinedload
from sqlalchemy import or_
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()

app = Flask(__name__)

# ===============================
# CONFIGURACIÓN SEGURA

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ===============================
# BASE DE DATOS (SOLO POSTGRESQL)

DATABASE_URL = os.environ.get("DATABASE_URL")
# if not DATABASE_URL:
#     raise RuntimeError("arca_db_hvbw")
DATABASE_URL = DATABASE_URL or "sqlite:///test_local.db"  # fallback temporal

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)
SessionLocal = scoped_session(sessionmaker(bind=engine))

# ================== Login ==================
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.get(User, int(user_id))
    finally:
        db.close()

def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if roles and current_user.role not in roles:
                flash("No autorizado", "error")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        return wrapper
    return deco

# =========== PARA IMAGEN DE PRODUCTOS EN INVENTARIO ==========#
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ================== Models ==================
Base = declarative_base()

class User(Base, UserMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="staff")  # admin | staff
    created_at = Column(DateTime, default=func.now())

    def set_password(self, pwd): self.password_hash = generate_password_hash(pwd)
    def check_password(self, pwd): return check_password_hash(self.password_hash, pwd)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100))
    price = Column(Float, default=0.0)
    quantity = Column(Float, default=0.0)
    notes = Column(Text)
    dog_size = Column(String(10), default='M')  # S, M, L, XL
    image = Column(String(200))  # ← nuevo campo para la imagen
    caducidad = Column(DateTime) 

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    status = Column(String(20), default="open")  # open | done | canceled
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")
    internal = Column(Boolean, default=False)
    internal_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class SaleItem(Base):
    __tablename__ = "sale_items"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    qty = Column(Float, default=1.0)
    price = Column(Float, default=0.0)
    sale = relationship("Sale", back_populates="items")
    product = relationship("Product")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=func.now())
    user_email = Column(String(120))
    action = Column(String(50))  # login, logout, create_product, update_product, etc.
    entity = Column(String(50))
    data = Column(Text)  # JSON

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)

# ================== NUEVOS MODELOS: Supplier & Contact ==================
class Supplier(Base):
    """Modelo para Proveedores"""
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    rfc = Column(String(20), unique=True, nullable=True)
    email = Column(String(120), nullable=True)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    contacts = relationship("Contact", back_populates="supplier", cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'rfc': self.rfc,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'notes': self.notes,
            'contacts_count': len(self.contacts) if self.contacts else 0
        }

class Contact(Base):
    """Modelo para Contactos de Proveedores"""
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    name = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(120), nullable=True)
    position = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    
    supplier = relationship("Supplier", back_populates="contacts")
    
    def to_dict(self):
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'position': self.position,
            'notes': self.notes
        }

#class Appointment(Base):
#    __tablename__ = 'appointments'
#    id = Column(Integer, primary_key=True)
#    client_name = Column(String(200), nullable=False)
#    appointment_date = Column(DateTime, default=func.now())
#    return_date = Column(DateTime, nullable=True)
#    notes = Column(Text)
#    created_at = Column(DateTime, default=func.now())

#Estetica_form#
class EsteticaService(Base):
    __tablename__ = 'estetica_services'
    
    id = Column(Integer, primary_key=True)
    fecha = Column(DateTime)
    propietarionombre = Column(String(200), nullable=False)
    propietariodireccion = Column(String(300))
    propietarionumero = Column(String(10))  # Solo 10 dígitos
    mascotanombre = Column(String(200), nullable=False)
    mascotasexo = Column(String(20))  # masculino/femenino
    mascotaedad = Column(String(2))   # 01-99
    mascotaraza = Column(String(200))
    mascotacolor = Column(String(100))
    mascotatamano = Column(Float)     # En cm
    observaciones = Column(Text)
    tipocorte = Column(String(50), nullable=True)
    precio = Column(Float)
    servicio = Column(String(100))
    created_at = Column(DateTime, default=func.now())

class Owner(Base):
    __tablename__ = 'owners'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    address = Column(String(200))
    postal_code = Column(String(10))
    city = Column(String(50))
    phone = Column(String(20))
    notes = Column(Text)
    pets = relationship("Pet", back_populates="owner")  # Relación uno-a-muchos 

class Pet(Base):
    __tablename__ = 'pets'
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    # Elimina owner_name: redundante y propenso a errores 
    breed = Column(String(200))
    color = Column(String(100))
    size = Column(String(20), default='M')
    species = Column(String(10), nullable=False)
    sex = Column(String(1), nullable=False)
    age = Column(Integer)
    photo = Column(String(200))
    notes = Column(Text)  # Agrega este campo si lo usas
    created_at = Column(DateTime, default=func.now())
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)  # No nullable
    records = relationship("ClinicalRecord", back_populates="pet", order_by="ClinicalRecord.date.desc()")
    owner = relationship("Owner", back_populates="pets")  # Relación muchos-a-uno 


class DocumentoMascota(Base):
    __tablename__ = 'documentos_mascotas'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    pet_id = Column(Integer, ForeignKey('pets.id'), nullable=False)
    tipo_documento = Column(String(120), nullable=False)
    ruta_archivo = Column(String(255), nullable=False)
    fecha_carga = Column(DateTime, default= datetime.utcnow)
    owner = relationship('Owner')
    pet = relationship('Pet')

    @property
    def cliente(self):
        return self.owner
    
    @property
    def mascota(self):
        return self.pet

class ClinicalRecord(Base):
    __tablename__ = 'clinical_records'
    id = Column(Integer, primary_key=True)
    pet_id = Column(Integer, ForeignKey('pets.id'), nullable=False)
    date = Column(DateTime)
    weight = Column(Float, nullable=True)  # Peso en kg
    height = Column(Float, nullable=True)  # Talla en cm
    temperature = Column(Float, nullable=True)  # Temperatura en °C
    dewormed = Column(DateTime, nullable=True)  # Fecha desparasitado
    vaccinated = Column(DateTime, nullable=True)  # Fecha vacunado
    surgery = Column(String(255), nullable=True)  # Tipo de cirugía
    last_surgery = Column(DateTime, nullable=True)  # Fecha última cirugía
    created_at = Column(DateTime, default=func.now())
    pet = relationship("Pet", back_populates="records")



class AppointmentBase(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    duration = Column(Integer, default=30)      # minutos
    motivo = Column(String(255), nullable=False)
    tipo = Column(String(50), default="Consulta")
    vet = Column(String(100), nullable=False)
    pet_id = Column(Integer, ForeignKey("pets.id"), nullable=False)

    pet = relationship("Pet")  # ya tienes PetBase definido

Base.metadata.create_all(engine) #<--IMPORTANTE

@app.route("/citas")
@login_required
def citas():
    db = SessionLocal()
    try:
        # ← AQUÍ ESTÁ LA MAGIA: carga pet.owner en UNA consulta
        citas = (db.query(AppointmentBase)
                .options(joinedload(AppointmentBase.pet).joinedload(Pet.owner))
                .order_by(AppointmentBase.date.asc())
                .all())
        return render_template("citas.html", citas=citas)
    finally:
        db.close()


@app.route("/citas/nueva", methods=["GET", "POST"])
@login_required
def cita_nueva():
    db = SessionLocal()
    try:
        pets = (db.query(Pet)
               .options(joinedload(Pet.owner))
               .order_by(Pet.name.asc())
               .all())

        if request.method == "POST":
            # 1. VALIDAR DATOS PRIMERO
            fecha_str = request.form.get("fecha")
            hora_str = request.form.get("hora")
            if not (fecha_str and hora_str):
                flash("Selecciona fecha y hora.", "error")
                return render_template("cita_form.html", pets=pets)

            # 2. CREAR LA CITA
            fecha_completa = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
            cita = AppointmentBase(
                date=fecha_completa,
                duration=int(request.form.get("duracion") or 30),
                motivo=request.form.get("motivo") or "",
                tipo=request.form.get("tipo") or "Consulta",
                vet=request.form.get("vet") or "",
                pet_id=int(request.form.get("pet_id"))
            )
            db.add(cita)
            db.commit()  # ← IMPORTANTE: COMMIT PRIMERO

            # 3. AHORA SÍ mandar WhatsApp (cita ya existe)
            enviar_recordatorio_whatsapp(cita, db)

            flash("✅ Cita creada y recordatorio enviado.", "success")
            return redirect(url_for("citas"))

        return render_template("cita_form.html", pets=pets)
    except Exception as e:
        if db:
            db.rollback()
        flash(f"Error: {str(e)}", "error")
        return render_template("cita_form.html", pets=pets)
    finally:
        db.close()

@app.route('/citas/<int:citaid>/editar', methods=['GET', 'POST'])
@login_required
def citaeditar(citaid):
    db = SessionLocal()
    try:
        cita = db.get(AppointmentBase, citaid)
        if not cita:
            flash('Cita no encontrada.', 'error')
            return redirect(url_for('citas'))
        
        pets = db.query(Pet).options(joinedload(Pet.owner)).order_by(Pet.name.asc()).all()
        
        if request.method == 'POST':
            fechastr = request.form.get('fecha')
            horastr = request.form.get('hora')
            if not fechastr or not horastr:
                flash('Selecciona fecha y hora.', 'error')
                return render_template('cita_form.html', pets=pets, cita=cita)
            
            fechacompleta = datetime.strptime(f'{fechastr} {horastr}', '%Y-%m-%d %H:%M')
            cita.date = fechacompleta
            cita.duration = int(request.form.get('duracion') or 30)
            cita.motivo = request.form.get('motivo') or ''
            cita.tipo = request.form.get('tipo') or 'Consulta'
            cita.vet = request.form.get('vet') or ''
            cita.pet_id = int(request.form.get('pet_id'))  # Corrección aquí: pet_id en lugar de petid
            
            db.commit()
            # enviarrecordatoriowhatsapp(cita, db)  # Reenvía recordatorio actualizado, descomenta si existe
            flash('Cita actualizada correctamente.', 'success')
            return redirect(url_for('citas'))
        
        return render_template('cita_form.html', pets=pets, cita=cita)
    
    except Exception as e:
        if db:
            db.rollback()
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('citas'))
    finally:
        db.close()


@app.route("/citas/<int:cita_id>/delete", methods=["POST"])
@login_required
def cita_delete(cita_id):
    db = SessionLocal()
    try:
        cita = db.get(AppointmentBase, cita_id)
        if not cita:
            flash("Cita no encontrada.", "error")
            return redirect(url_for("citas"))
        
        db.delete(cita)
        db.commit()
        flash("✅ Cita eliminada.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error: {str(e)}", "error")
    finally:
        db.close()
    return redirect(url_for("citas"))

def enviar_recordatorio_whatsapp(cita, db):
    try:
        pet = db.get(Pet, cita.pet_id)
        if not pet or not pet.owner or not pet.owner.phone:
            print("No se pudo enviar: falta teléfono")
            return

        fecha_local = cita.date.strftime("%d/%m/%Y")
        hora_local = cita.date.strftime("%H:%M")
        
        texto = f"""Recordatorio de cita
Fecha: {fecha_local}
Hora: {hora_local}
Clínica: Clínica
Atiende: {cita.vet}
Mascota: {pet.name}
Tipo: {cita.tipo}
Motivo: {cita.motivo or 'N/A'}"""

        # Enlace WhatsApp
        phone = pet.owner.phone.replace(" ", "").replace("-", "")
        url = f"https://wa.me/{phone}?text={quote_plus(texto)}"
        print("🔗 WhatsApp:", url)  # Para debug
        
    except Exception as e:
        print(f"Error WhatsApp: {e}")


@app.route("/historial-clinico")
@login_required
def historial_clinico():
    db = SessionLocal()
    try:
        q = request.args.get("q") or ""
        f = f"%{q}%"
        
        # Lista: carga owner para todos los pets
        pets = (db.query(Pet)
                .options(joinedload(Pet.owner))
                .filter(Pet.name.ilike(f))
                .order_by(Pet.name)
                .all())

        pet_id = request.args.get("petid")  # ← MOVER ARRIBA
        selected_pet = None
        records = []

        if pet_id:
            # Detalle: carga owner + records
            selected_pet = (db.query(Pet)
                           .options(joinedload(Pet.owner))
                           .options(joinedload(Pet.records))
                           .filter(Pet.id == int(pet_id))
                           .first())
            if selected_pet:
                records = selected_pet.records or []

        return render_template(
            "historial_clinico.html",
            pets=pets,
            selected_pet=selected_pet,
            records=records,
            q=q
        )
    finally:
        db.close()


@app.route('/historial-clinico/nueva-mascota', methods=['GET', 'POST'])
@login_required
@require_roles("admin","staff")
def nueva_mascota():
    if request.method == 'POST':
        db = None
        try:
            db = SessionLocal()
            form_data = request.form
            
            pet_name = form_data.get('petname', '').strip()
            species = form_data.get('species', '').strip()
            sex = form_data.get('sex', '').strip()
            owner_name = form_data.get('ownername', '').strip()
            
            if not all([pet_name, species, sex, owner_name]):
                flash('Faltan campos obligatorios: nombre mascota, especie, sexo o dueño.', 'error')
                return render_template('pet_form.html')  # ← RETORNA AQUÍ 
            
            owner = Owner(
                name=owner_name,
                address=form_data.get('address'),
                postal_code=form_data.get('postalcode'),
                city=form_data.get('city'),
                phone=form_data.get('phone'),
                notes=form_data.get('notes', '')
            )
            db.add(owner)
            db.flush()

            pet = Pet(
                name=pet_name,
                breed=form_data.get('breed'),
                color=form_data.get('color'),
                size=form_data.get('size', 'M'),
                species=species,
                sex=sex.upper(),
                age=int(form_data.get('age') or 0),
                notes=form_data.get('notes', ''),
                photo=form_data.get('photo'),
                owner=owner
            )
            db.add(pet)
            db.commit()
            db.close()
            flash('¡Mascota y dueño creados exitosamente!', 'success')
            return redirect(url_for('historial_clinico'))
            
        except Exception as e:
            if db:
                db.rollback()
                db.close()
            flash(f'Error al guardar: {str(e)}', 'error')
            return render_template('pet_form.html')  # ← RETORNA AQUÍ
    
    # GET: Siempre muestra el form
    return render_template('pet_form.html')




@app.route('/historial-clinico/<int:pet_id>/nuevo-registro', methods=['GET', 'POST'])
@login_required
@require_roles('admin', 'staff')
def nuevo_registro(pet_id):
    db = SessionLocal()
    try:
        pet = db.get(Pet, pet_id)
        if not pet:
            abort(404)
        
        if request.method == 'POST':
            try:
                record = ClinicalRecord(
                    pet_id=pet_id,
                    date=datetime.strptime(request.form.get('date'), '%Y-%m-%dT%H:%M') if request.form.get('date') else None,
                    weight=float(request.form.get('weight')) if request.form.get('weight') else None,
                    height=float(request.form.get('height')) if request.form.get('height') else None,
                    temperature=float(request.form.get('temperature')) if request.form.get('temperature') else None,
                    dewormed=datetime.strptime(request.form.get('dewormed'), '%Y-%m-%d').date() if request.form.get('dewormed') else None,
                    vaccinated=datetime.strptime(request.form.get('vaccinated'), '%Y-%m-%d').date() if request.form.get('vaccinated') else None,
                    surgery=request.form.get('surgery'),
                    last_surgery=datetime.strptime(request.form.get('last_surgery'), '%Y-%m-%d').date() if request.form.get('last_surgery') else None
                )
                db.add(record)
                db.commit()
                flash('Registro clínico guardado', 'success')
                q = request.args.get('q', '')
                return redirect(url_for('historial_clinico', petid=pet_id, q=q))
            except Exception as e:
                db.rollback()
                flash(f'Error: {e}', 'error')
        
        return render_template('record_form.html', pet=pet)  # Cambia a record_form.html
        
    finally:
        db.close()

@app.route('/historial-clinico/<int:petid>/editar-foto', methods=['GET', 'POST'])
@login_required
def editar_foto(pet_id):
    db = SessionLocal()
    try:
        pet = db.get(Pet, pet_id)
        if not pet:
            abort(404)
        if request.method == 'POST':
            if 'foto' in request.files:
                file = request.files['foto']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'pets_{pet_id}_{filename}')
                    file.save(filepath)
                    if pet.photo and os.path.exists(pet.photo):
                        os.remove(pet.photo)  # Borra anterior
                    pet.photo = filepath  # Guarda ruta relativa
            db.commit()
            flash('Foto actualizada correctamente.', 'success')
            return redirect(url_for('historial_clinico', petid=pet_id))
        return render_template('editar_foto.html', pet=pet)
    except Exception as e:
        if db:
            db.rollback()
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('historial_clinico', petid=pet_id))
    finally:
        db.close()


import sqlite3
from flask import request, redirect, url_for, flash, render_template, g
from contextlib import closing

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('vet.db')  # Cambia por nombre real de tu DB (busca en app.py)
        g.db.row_factory = sqlite3.Row  # Para dict-like rows
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()

@app.route('/editar_registro/<int:record_id>', methods=['GET', 'POST'])
def editar_registro(record_id):
    db = get_db()
    pet_id = request.args.get('pet_id') or request.form.get('pet_id')
    q = request.args.get('q') or request.form.get('q', '')
    
    if request.method == 'POST':
        cur = db.cursor()
        cur.execute('''
            UPDATE clinical_records SET 
                weight=?, height=?, temperature=?, dewormed=?, vaccinated=?, surgery=?, last_surgery=?
            WHERE id=?
        ''', (
            float(request.form['weight']) if request.form['weight'] else None,
            float(request.form['height']) if request.form['height'] else None,
            float(request.form['temperature']) if request.form['temperature'] else None,
            request.form['dewormed'] or None,
            request.form['vaccinated'] or None,
            request.form['surgery'],
            request.form['last_surgery'] or None,
            record_id
        ))
        db.commit()
        flash('Registro actualizado')
        return redirect(url_for('historial_clinico', petid=pet_id, q=q))
    
    cur = db.cursor()
    cur.execute('SELECT * FROM clinical_records WHERE id=?', (record_id,))
    record = cur.fetchone()
    if not record:
        flash('Registro no encontrado')
        return redirect(url_for('historial_clinico', petid=pet_id, q=q))
    
    return render_template('editar_registro.html', record=dict(record), pet_id=pet_id, q=q)


@app.route('/eliminar_registro/<int:record_id>', methods=['POST'])
def eliminar_registro(record_id):
    db = get_db()
    pet_id = request.form.get('pet_id')
    q = request.form.get('q', '')
    cur = db.cursor()
    cur.execute('DELETE FROM clinical_records WHERE id=?', (record_id,))
    db.commit()
    flash('Registro eliminado')
    return redirect(url_for('historial_clinico', pet_id=pet_id, q=q))



# Seed admin user
def seed_admin():
    db = SessionLocal()
    try:
        if not db.query(User).filter_by(email="admin@arca.local").first():
            u = User(email="admin@arca.local", role="admin")
            u.set_password("admin123")
            db.add(u)
            db.commit()
    finally:
        db.close()

seed_admin()

# =============== CONTACTOS ================= #
@app.route("/contacts")
@login_required
def contacts_list():
    db = SessionLocal()
    try:
        q = (request.args.get("q") or "").strip()
        base = (
            db.query(Contact)
              .options(joinedload(Contact.supplier))
              .join(Supplier)
        )

        if q:
            like = f"%{q}%"
            base = base.filter(
                or_(
                    Contact.name.ilike(like),
                    Contact.phone.ilike(like),
                    Contact.email.ilike(like),
                    Supplier.name.ilike(like) # ← búsqueda por proveedor
                )
            )
        contacts = base.order_by(Contact.name).all()
        return render_template("contacts_list.html", contacts=contacts, q=q)
    finally:
        db.close()

# ================== Routes: Autorizaciones ==================
from sqlalchemy.orm import joinedload
@app.route('/autorizaciones')
@login_required
def autho():
    db = SessionLocal()
    try:
        # ✅ Carga TODAS las relaciones necesarias ANTES de cerrar
        documentos = db.query(DocumentoMascota) \
            .options(
                joinedload(DocumentoMascota.owner),
                joinedload(DocumentoMascota.pet)
            ) \
            .all()
        
        # IMPORTANTE: Accede a los datos AQUÍ, mientras la sesión está abierta
        # Esto "activa" los datos relacionados
        for doc in documentos:
            _ = doc.owner # Fuerza la carga
            _ = doc.pet # Fuerza la carga
        
        return render_template('autho.html', documentos=documentos)
    finally:
        db.close()

@app.route('/documentos')
@login_required
def documentos():
    db = SessionLocal()
    try:
        documentos = db.query(DocumentoMascota) \
            .options(
                joinedload(DocumentoMascota.owner),
                joinedload(DocumentoMascota.pet)
            ).all()
        return render_template('nuevo_doc.html', documentos=documentos)
    finally:
        db.close()


from mimetypes import guess_type
from flask import send_from_directory, abort
import os
@app.route('/documentos/<int:doc_id>/preview')
def documentos_preview(doc_id):
    db = SessionLocal()
    try:
        doc = db.get(DocumentoMascota, doc_id) # Usa DocumentoMascota
        if not doc:
            abort(404, "Documento no encontrado")
        if not doc.ruta_archivo:
            abort(404, "No hay archivo asociado")
        ruta_absoluta = os.path.abspath(doc.ruta_archivo)
        if not os.path.exists(ruta_absoluta) or not os.path.isfile(ruta_absoluta):
            abort(404, "Archivo no encontrado en el servidor")
        directorio_base = os.path.dirname(ruta_absoluta)
        nombre_archivo = os.path.basename(ruta_absoluta)
        mimetype, _ = guess_type(ruta_absoluta)
        if not mimetype:
            mimetype = 'application/octet-stream'
        return send_from_directory(
            directorio_base,
            nombre_archivo,
            as_attachment=False,
            mimetype=mimetype
        )
    finally:
        db.close()

@app.route('/documentos/crear', methods=['GET', 'POST'])
@login_required
def documentos_crear():
    db = SessionLocal()
    try:
        if request.method == 'POST':
            owner_id = request.form.get('owner_id')
            pet_id = request.form.get('pet_id')
            tipo_documento = request.form.get('tipo_documento')
            
            # Validar que tenga archivo
            archivo = request.files.get('archivo')
            if not archivo or not archivo.filename:
                flash('Debes subir un archivo', 'error')
                return redirect(url_for('documentos_crear'))
            
            # Guardar archivo
            filename = secure_filename(archivo.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"docs_{owner_id}_{filename}")
            archivo.save(filepath)
            
            # Crear documento
            doc = DocumentoMascota(
                owner_id=int(owner_id),
                pet_id=int(pet_id),
                tipo_documento=tipo_documento,
                ruta_archivo=filepath,
                fecha_carga=datetime.utcnow()
            )
            db.add(doc)
            db.commit()
            
            flash('Documento guardado correctamente', 'success')
            return redirect(url_for('documentos'))
        pass
        
        # GET: Cargar con relaciones si es necesario
        owners = db.query(Owner) \
            .options(joinedload(Owner.pets)) \
            .order_by(Owner.name) \
            .all()
        
        pets = db.query(Pet) \
            .options(joinedload(Pet.owner)) \
            .order_by(Pet.name) \
            .all()
        
        return render_template('crear_documento.html', owners=owners, pets=pets)
    finally:
        db.close()

# ================== Routes: Documentos (CRUD Completo) ==================
@app.route('/documentos/<int:doc_id>/editar', methods=['GET', 'POST'])
@login_required
def documentos_editar(doc_id):
    db = SessionLocal()
    try:
        doc = db.query(DocumentoMascota)\
            .options(joinedload(DocumentoMascota.owner), joinedload(DocumentoMascota.pet))\
            .get(doc_id) or abort(404)
        
        if request.method == 'POST':
            # Si se sube un nuevo archivo, reemplazar el anterior
            archivo = request.files.get('archivo')
            if archivo and archivo.filename:
                filename = secure_filename(archivo.filename)
                # Eliminar archivo anterior si existe
                if doc.ruta_archivo and os.path.exists(doc.ruta_archivo):
                    os.remove(doc.ruta_archivo)
                # Guardar nuevo archivo
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"docs_{doc.owner_id}_{filename}")
                archivo.save(filepath)
                doc.ruta_archivo = filepath
            
            # Actualizar otros campos
            doc.tipo_documento = request.form.get('tipo_documento', doc.tipo_documento)
            doc.owner_id = int(request.form.get('owner_id', doc.owner_id))
            doc.pet_id = int(request.form.get('pet_id', doc.pet_id))
            
            db.commit()
            audit('update_documento', 'documentos', {'id': doc_id, 'owner': doc.owner.name})
            flash('Documento actualizado correctamente', 'success')
            return redirect(url_for('documentos'))
        
        # GET: Cargar TODAS las relaciones ANTES de renderizar
        owners = db.query(Owner).options(joinedload(Owner.pets)).order_by(Owner.name).all()
        pets = db.query(Pet).options(joinedload(Pet.owner)).order_by(Pet.name).all()
        
        # IMPORTANTE: Acceder a los datos AQUÍ mientras la sesión está abierta
        doc_owner_name = doc.owner.name if doc.owner else "—"
        doc_pet_name = doc.pet.name if doc.pet else "—"
        
        return render_template('editar_documento.html',
                             doc=doc,
                             doc_owner_name=doc_owner_name,
                             doc_pet_name=doc_pet_name,
                             owners=owners,
                             pets=pets)
    finally:
        db.close()

@app.route('/documentos/<int:doc_id>/eliminar', methods=['POST'])
@login_required
def documentos_eliminar(doc_id):
    """Eliminar un documento"""
    db = SessionLocal()
    try:
        doc = db.query(DocumentoMascota)\
            .options(joinedload(DocumentoMascota.owner))\
            .get(doc_id) or abort(404)
        
        # IMPORTANTE: Guardar info ANTES de eliminar
        owner_name = doc.owner.name if doc.owner else "Desconocido"
        ruta_archivo = doc.ruta_archivo
        
        # Eliminar archivo física si existe
        if ruta_archivo and os.path.exists(ruta_archivo):
            try:
                os.remove(ruta_archivo)
            except Exception as e:
                print(f"Error eliminando archivo: {e}")
        
        # Eliminar registro de BD
        db.delete(doc)
        db.commit()
        
        audit('delete_documento', 'documentos', {'id': doc_id, 'owner': owner_name})
        flash('Documento eliminado correctamente', 'success')
    except Exception as e:
        db.rollback()
        flash(f'Error al eliminar: {e}', 'error')
    finally:
        db.close()
    
    return redirect(url_for('documentos'))

@app.route('/documentos/<int:doc_id>/descargar')
@login_required
def documentos_descargar(doc_id):
    """Descargar un documento"""
    db = SessionLocal()
    try:
        doc = db.query(DocumentoMascota).get(doc_id) or abort(404)
        
        if doc.ruta_archivo and os.path.exists(doc.ruta_archivo):
            return send_file(doc.ruta_archivo, as_attachment=True)
        else:
            flash('Archivo no encontrado', 'error')
            return redirect(url_for('documentos'))
    finally:
        db.close()


@app.route('/static/downloads/<filename>')
@login_required
def download_pdf(filename): # ← Solo 'filename', NO ruta completa
    """Descarga PDF específico para autorizaciones"""
    return send_from_directory('static/downloads', filename, as_attachment=True)

# ================== Helpers ==================
def audit(action, entity, payload=None):
    db = SessionLocal()
    try:
        a = AuditLog(
            user_email=current_user.email if current_user.is_authenticated else None,
            action=action,
            entity=entity,
            data=json.dumps(payload or {}, ensure_ascii=False)
        )
        db.add(a)
        db.commit()
    finally:
        db.close()

def get_setting(db, key, default=None):
    s = db.get(Setting, key)
    return s.value if s else default

def set_setting(db, key, value):
    s = db.get(Setting, key)
    if not s:
        s = Setting(key=key, value=value)
        db.add(s)
    else:
        s.value = value
    return s

# Navigation helpers
@app.context_processor
def inject_nav_helpers():
    def safe_url(endpoint, **kwargs):
        try:
            return url_for(endpoint, **kwargs)
        except Exception:
            return "#"
        return dict(safeurl=safeurl)
    
    # Brand info
    name = "El Arca De Charly"
    logo_rel = "img/arca_logo.png"
    db = SessionLocal()
    try:
        name = get_setting(db, "brand_name", name) or name
        logo_rel = get_setting(db, "brand_logo", logo_rel) or logo_rel
    finally:
        db.close()
    
    return dict(safe_url=safe_url, brand_name=name, brand_logo=logo_rel)

# ================== Routes: Auth ==================
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pwd = request.form.get("password") or ""
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(email=email).first()
            if u and u.check_password(pwd):
                login_user(u)
                audit("login","auth",{"email":email})
                return redirect(url_for("index"))
            flash("Credenciales inválidas","error")
        finally:
            db.close()
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    audit("logout","auth",{})
    logout_user()
    return redirect(url_for("login"))

# ================== Routes: Index ==================
@app.route("/")
@login_required
def index():
    return render_template("index.html")

# ================== Routes: Inventory ==================
@app.route("/inventory")
@login_required
@require_roles('admin')
def inventory_list():
    db = SessionLocal()
    try:
        q = (request.args.get("q") or "").strip()
        base = db.query(Product)
        if q:
            base = base.filter(Product.name.ilike(f"%{q}%") | Product.code.ilike(f"%{q}%"))
        items = base.order_by(Product.name).all()
        return render_template("inventory_list.html", items=items, q=q)
    finally:
        db.close()

@app.route("/inventory/new", methods=["GET","POST"])
@login_required
@require_roles("admin","staff")
def inventory_new():
    if request.method == "POST":
        db = SessionLocal()
        try:
            image_filename = None
            if 'image' in request.files:
                file = request.files['image']
                if file.filename:
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    image_filename = filename
            caducidad_str = (request.form.get("caducidad") or "").strip()
            caducidad = None
            if caducidad_str:
                caducidad = datetime.strptime(caducidad_str, "%Y-%m-%d").date()
            p = Product(
                image=image_filename,
                code=(request.form.get("code") or "").strip(),
                name=(request.form.get("name") or "").strip(),
                category=(request.form.get("category") or "").strip(),
                price=float(request.form.get("price") or 0),
                quantity=float(request.form.get("quantity") or 0),
                notes=(request.form.get("notes") or "").strip(),
                caducidad=caducidad
            )
            db.add(p); db.commit()
            audit("create_product","inventory",{"id":p.id,"code":p.code})
            flash("Producto creado","success")
            return redirect(url_for("inventory_list"))
        except Exception as e:
            db.rollback(); flash(f"Error: {e}", "error")
        finally:
            db.close()
    return render_template("inventory_form.html", item=None)

@app.route("/inventory/<int:pid>/edit", methods=["GET","POST"])
@login_required
@require_roles("admin","staff")
def inventory_edit(pid):
    db = SessionLocal()
    try:
        p = db.get(Product, pid) or abort(404)
        if request.method == "POST":
            p.image = (request.form.get("image") or "").strip()
            p.code = (request.form.get("code") or "").strip()
            p.name = (request.form.get("name") or "").strip()
            p.category = (request.form.get("category") or "").strip()
            p.price = float(request.form.get("price") or 0)
            p.quantity = float(request.form.get("quantity") or 0)
            p.notes = (request.form.get("notes") or "").strip()
            caducidad_str = (request.form.get("caducidad") or "").strip()
            p.caducidad = None
            if caducidad_str:
                p.caducidad = datetime.strptime(caducidad_str, "%Y-%m-%d").date()
            db.commit()
            audit("update_product","inventory",{"id":p.id,"code":p.code})
            flash("Producto actualizado","success")
            return redirect(url_for("inventory_list"))
        return render_template("inventory_form.html", item=p)
    finally:
        db.close()


@app.route("/inventory/<int:pid>/delete", methods=["POST"])
@login_required
@require_roles("admin")
def inventory_delete(pid):
    db = SessionLocal()
    try:
        p = db.get(Product, pid) or abort(404)
        db.delete(p); db.commit()
        audit("delete_product","inventory",{"id":pid})
        flash("Producto eliminado","success")
    finally:
        db.close()
    return redirect(url_for("inventory_list"))

# CSV export/import
@app.route("/admin/inventory/export")
@login_required
@require_roles("admin")
def inventory_export():
    db = SessionLocal()
    try:
        rows = db.query(Product).order_by(Product.name).all()
        sio = io.StringIO()
        w = csv.writer(sio)
        w.writerow(["code","name","category","price","quantity","notes"])
        for p in rows:
            w.writerow([p.code or "", p.name or "", p.category or "", p.price or 0, p.quantity or 0, (p.notes or "").replace("\n"," ")])
        bio = io.BytesIO(sio.getvalue().encode("utf-8-sig"))
        return send_file(bio, as_attachment=True, download_name="inventario.csv")
    finally:
        db.close()

@app.route("/admin/inventory/import", methods=["POST"])
@login_required
@require_roles("admin")
def inventory_import():
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Sube un CSV","error"); return redirect(url_for("admin_datos"))
    db = SessionLocal()
    created = updated = 0
    try:
        text = io.TextIOWrapper(f.stream, encoding="utf-8-sig")
        reader = csv.DictReader(text)
        for row in reader:
            code = (row.get("code") or "").strip()
            if not code: continue
            p = db.query(Product).filter_by(code=code).first()
            if not p:
                p = Product(code=code, name=(row.get("name") or "").strip())
                db.add(p); created += 1
            else:
                updated += 1
            p.category = (row.get("category") or "").strip()
            try: p.price = float(row.get("price") or 0)
            except: p.price = 0
            try: p.quantity = float(row.get("quantity") or 0)
            except: p.quantity = 0
            p.notes = (row.get("notes") or "").strip()
        db.commit()
        flash(f"Importación OK. Nuevos: {created}, actualizados: {updated}", "success")
    except Exception as e:
        db.rollback(); flash(f"Error importando CSV: {e}", "error")
    finally:
        db.close()
    return redirect(url_for("admin_datos"))

#========= IMAGEN Y CAMARA DE PRODUCTOS EN INVENTARIO =======#
from flask import request
@app.route('/inventory/add', methods=['POST'])
def add_inventory():
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            filename = secure_filename(file.filename)
            path = os.path.join('static/uploads/', filename)
            file.save(path)
            # Guarda 'path' en BD

# ================== Routes: Sales ==================
@app.route("/ventas/nueva", methods=["GET","POST"])
#@login_required
def nueva_venta():
    db = SessionLocal()
    try:
        sale = db.query(Sale).filter_by(status="open").order_by(Sale.id.desc()).first()
        if not sale:
            sale = Sale(status="open"); db.add(sale); db.commit()
        if request.method == "POST":
            code = (request.form.get("code") or "").strip()
            qty = float(request.form.get("qty") or 1)
            prod = db.query(Product).filter_by(code=code).first()
            if not prod:
                flash("Producto no encontrado","error")
            else:
                it = SaleItem(sale_id=sale.id, product_id=prod.id, qty=qty, price=prod.price)
                db.add(it); db.commit()
        items=(db.query(SaleItem).filter_by(sale_id=sale.id).options(joinedload(SaleItem.product)).all())
        total = sum(i.qty*i.price for i in items)
        

        discount_pct = float(request.form.get('discount_pct', 0) or 0) / 100
        total = total * (1 - discount_pct)

        return render_template("sale_new.html", sale=sale, items=items, total=total)
    finally:
        db.close()


@app.route('/ventas/interna', methods=['GET', 'POST'])
@login_required
def ventas_interna():
    db = SessionLocal()
    try:
        # Solo staff puede crear ventas internas
        if current_user.role != 'staff':
            flash('Solo staff para ventas internas', 'error')
            return redirect(url_for('nueva_venta'))
            
        sale = db.query(Sale).filter_by(status='open').order_by(Sale.id.desc()).first()
        if not sale:
            sale = Sale(status='open', internal=True)  # ← Marca como interna
            db.add(sale)
            db.commit()
            
        if request.method == 'POST':
            code = request.form.get('code') or ''
            qty = float(request.form.get('qty') or 1)
            prod = db.query(Product).filter_by(code=code).first()
            if not prod:
                flash('Producto no encontrado', 'error')
            else:
                it = SaleItem(sale_id=sale.id, product_id=prod.id, qty=qty, price=prod.price)
                db.add(it)
                db.commit()
                
        items = db.query(SaleItem).filter_by(sale_id=sale.id).options(joinedload(SaleItem.product)).all()
        total = sum(i.qty * i.price for i in items)
        discount_pct = float(request.form.get('discount_pct', 0) or 0) / 100
        total = total * (1 - discount_pct)
        
        return render_template('sale_new.html', sale=sale, items=items, total=total)
    finally:
        db.close()


@app.post("/ventas/<int:sale_id>/item/<int:item_id>/delete")
#@login_required
def venta_item_delete(sale_id, item_id):
    db = SessionLocal()
    try:
        it = db.get(SaleItem, item_id) or abort(404)
        db.delete(it); db.commit()
        return redirect(url_for("nueva_venta"))
    finally:
        db.close()

@app.post('/ventas/<int:sale_id>/finalizar')
#@login_required
def ventafinalizar(sale_id):
    db = SessionLocal()
    try:
        sale = db.get(Sale, sale_id) or abort(404)
        if sale.status != 'open':
            flash('La venta ya fue cerrada', 'error')
            return redirect(url_for('nueva_venta'))
        
        # ✅ GUARDAR DATOS ANTES del commit
        items_data = []
        for it in sale.items:
            prod = db.get(Product, it.product_id)
            if prod:
                prod.quantity = max(0.0, prod.quantity or 0.0 - it.qty or 0.0)
            # Guardar info para audit SIN acceder a lazy loading
            items_data.append({
                'product_id': it.product_id,
                'code': getattr(it.product, 'code', 'N/A') if it.product else 'N/A',  # Seguro
                'qty': it.qty
            })
        
        discountpct = float(request.form.get('discountpct', 0) or 0) / 100
        sale.total = sum(i.qty * i.price for i in sale.items) * (1 - discountpct)
        sale.status = 'done'
        
        db.commit()
        
        # ✅ Audit con datos ya guardados (SESION ABIERTA)
        audit('finalizesale', 'sales', {
            'sale_id': sale.id, 
            'items': items_data
        })
        flash('Venta finalizada', 'success')
        
    except Exception as e:
        db.rollback()
        flash(f'Error: {e}', 'error')
    finally:
        db.close()
    
    return redirect(url_for('nueva_venta'))


# ================== Routes: Users (admin) ==================
@app.route("/users")
@login_required
@require_roles("admin")
def users_list():
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        return render_template("users_list.html", users=users)
    finally:
        db.close()

@app.route("/users/new", methods=["GET","POST"])
@login_required
@require_roles("admin")
def users_new():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        role = (request.form.get("role") or "staff").strip()
        pwd1 = request.form.get("password") or ""
        db = SessionLocal()
        try:
            if db.query(User).filter_by(email=email).first():
                flash("Ya existe ese usuario","error")
            else:
                u = User(email=email, role=role); u.set_password(pwd1)
                db.add(u); db.commit()
                flash("Usuario creado","success")
                return redirect(url_for("users_list"))
        finally:
            db.close()
    return render_template("user_form.html", user=None)

@app.route("/users/<int:uid>/edit", methods=["GET","POST"])
@login_required
@require_roles("admin")
def users_edit(uid):
    db = SessionLocal()
    try:
        u = db.get(User, uid) or abort(404)
        if request.method == "POST":
            u.email = (request.form.get("email") or "").strip().lower()
            u.role = (request.form.get("role") or "staff").strip()
            pwd = request.form.get("password") or ""
            if pwd: u.set_password(pwd)
            db.commit()
            flash("Usuario actualizado","success")
            return redirect(url_for("users_list"))
        return render_template("user_form.html", user=u)
    finally:
        db.close()

@app.post("/users/<int:uid>/delete")
@login_required
@require_roles("admin")
def users_delete(uid):
    db = SessionLocal()
    try:
        u = db.get(User, uid) or abort(404)
        db.delete(u); db.commit()
        flash("Usuario eliminado","success")
    finally:
        db.close()
    return redirect(url_for("users_list"))

# ================== Routes: Reports (Audit) ==================
@app.route("/reportes/auditoria")
@login_required
def audit_list():
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(500).all()
        return render_template("audit_list.html", rows=rows)
    finally:
        db.close()

# ================== Routes: Admin ==================
@app.route("/admin/datos")
@login_required
@require_roles("admin")
def admin_datos():
    return render_template("admin_datos.html")

@app.route("/admin/backup")
@login_required
@require_roles("admin")
def admin_backup():
    db_path = DATABASE_URL.replace("sqlite:///","") if DATABASE_URL.startswith("sqlite") else "vet.db"
    if not os.path.exists(db_path):
        flash("No se encuentra vet.db","error")
        return redirect(url_for("admin_datos"))
    return send_file(db_path, as_attachment=True, download_name="vet.db")

@app.route("/admin/config", methods=["GET","POST"])
@login_required
@require_roles("admin")
def admin_config():
    os.makedirs(os.path.join("static","uploads"), exist_ok=True)
    db = SessionLocal()
    try:
        if request.method == "POST":
            name = (request.form.get("brand_name") or "").strip()
            if name: set_setting(db, "brand_name", name)
            f = request.files.get("brand_logo")
            if f and f.filename:
                ext = os.path.splitext(f.filename)[1].lower()
                if ext in [".png",".jpg",".jpeg",".webp"]:
                    path = os.path.join("static","uploads","brand_logo"+ext)
                    f.save(path)
                    set_setting(db, "brand_logo", "uploads/"+os.path.basename(path))
            db.commit()
            flash("Configuración guardada","success")
        name = get_setting(db,"brand_name","El Arca De Charly")
        logo = get_setting(db,"brand_logo","img/arca_logo.png")
        return render_template("admin_config.html", name=name, logo=logo)
    finally:
        db.close()

# Hardware detection - SOLO Windows (local)
IS_WINDOWS = platform.system() == "Windows"

win32print = None
win32con = None
_wmi = None
list_ports = None

if IS_WINDOWS:
    try:
        import win32print
        import win32con
    except ImportError:
        pass  # No hay pywin32 instalado, ignora

    try:
        import wmi as _wmi
    except ImportError:
        pass

    try:
        from serial.tools import list_ports
    except ImportError:
        pass

def hw_detect_printers():
    names, default = [], None
    if IS_WINDOWS and win32print:
        try:
            default = win32print.GetDefaultPrinter()
            for flags in (win32print.PRINTER_ENUM_LOCAL, win32print.PRINTER_ENUM_CONNECTIONS):
                for p in win32print.EnumPrinters(flags):
                    names.append(p[2])
            names = sorted(set(names))
        except Exception:
            pass
    return default, names

def hw_detect_com_ports():
    if list_ports:
        return [p.device for p in list_ports.comports()]
    return []

def hw_list_hid_hint():
    hint = []
    if IS_WINDOWS and _wmi:
        try:
            c = _wmi.WMI()
            for d in c.Win32_PnPEntity(PNPClass="HIDClass"):
                hint.append(d.Name)
        except Exception:
            pass
    return hint

def _send_raw_to_printer(data_bytes: bytes, printer_name: str = None):
    if not (IS_WINDOWS and win32print):
        raise RuntimeError("Impresión RAW solo en Windows con pywin32")
    if not printer_name:
        printer_name = win32print.GetDefaultPrinter()
    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Prueba", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, data_bytes)
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)

@app.route("/admin/hardware", methods=["GET"])
@login_required
@require_roles("admin")
def admin_hardware():
    default_prn, printers = hw_detect_printers()
    coms = hw_detect_com_ports()
    hid_list = hw_list_hid_hint()
    return render_template("admin_hardware.html",
        default_prn=default_prn, printers=printers,
        coms=coms, hid_list=hid_list, is_windows=IS_WINDOWS)

@app.post("/admin/hardware/print_test")
@login_required
@require_roles("admin")
def hardware_print_test():
    if not (IS_WINDOWS and win32print):
        flash("Solo disponible en Windows con pywin32 instalado", "error")
        return redirect(url_for("admin_hardware"))
    prn = request.form.get("printer") or None
    payload = (
        b"EL ARCA DE CHARLY\r\n"
        b"Prueba de impresora\r\n"
        b"--------------------\r\n"
        b"OK\r\n\r\n"
        b"\x1D\x56\x42\x10"
    )
    try:
        _send_raw_to_printer(payload, prn)
        flash("Impresión enviada","success")
    except Exception as e:
        flash(f"Error imprimiendo: {e}", "error")
    return redirect(url_for("admin_hardware"))

@app.post("/admin/hardware/open_drawer")
@login_required
@require_roles("admin")
def hardware_open_drawer():
    if not (IS_WINDOWS and win32print):
        flash("Solo disponible en Windows con pywin32 instalado", "error")
        return redirect(url_for("admin_hardware"))
    prn = request.form.get("printer") or None
    pulse = b"\x1B\x70\x00\x3C\xFF"  # ESC p m t1 t2
    try:
        _send_raw_to_printer(pulse, prn)
        flash("Pulso enviado (cajón)","success")
    except Exception as e:
        flash(f"Error abriendo cajón: {e}", "error")
    return redirect(url_for("admin_hardware"))

# ================== NUEVAS RUTAS: Suppliers & Contacts ==================
@app.route("/suppliers")
@login_required
def suppliers_list():
    """Lista de proveedores con búsqueda"""
    db = SessionLocal()
    try:
        q = (request.args.get("q") or "").strip()
        base = db.query(Supplier)
        if q:
            base = base.filter(
                (Supplier.name.ilike(f"%{q}%")) | 
                (Supplier.rfc.ilike(f"%{q}%")) |
                (Supplier.email.ilike(f"%{q}%"))
            )
        suppliers = base.order_by(Supplier.name).all()
        return render_template("suppliers_list.html", suppliers=suppliers, q=q)
    finally:
        db.close()


@app.route("/suppliers/new", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def suppliers_new():
    """Crear nuevo proveedor"""
    if request.method == "POST":
        db = SessionLocal()
        try:
            s = Supplier(
                name=(request.form.get("name") or "").strip(),
                rfc=(request.form.get("rfc") or "").strip(),
                email=(request.form.get("email") or "").strip(),
                phone=(request.form.get("phone") or "").strip(),
                address=(request.form.get("address") or "").strip(),
                city=(request.form.get("city") or "").strip(),
                notes=(request.form.get("notes") or "").strip()
            )
            db.add(s)
            db.commit()
            audit("create_supplier", "suppliers", {"id": s.id, "name": s.name})
            flash("Proveedor creado exitosamente", "success")
            return redirect(url_for("suppliers_list"))
        except Exception as e:
            db.rollback()
            flash(f"Error: {e}", "error")
        finally:
            db.close()
    return render_template("supplier_form.html", supplier=None)


@app.route("/suppliers/<int:sid>/edit", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def suppliers_edit(sid):
    """Editar proveedor"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        if request.method == "POST":
            s.name = (request.form.get("name") or "").strip()
            s.rfc = (request.form.get("rfc") or "").strip()
            s.email = (request.form.get("email") or "").strip()
            s.phone = (request.form.get("phone") or "").strip()
            s.address = (request.form.get("address") or "").strip()
            s.city = (request.form.get("city") or "").strip()
            s.notes = (request.form.get("notes") or "").strip()
            db.commit()
            audit("update_supplier", "suppliers", {"id": s.id, "name": s.name})
            flash("Proveedor actualizado", "success")
            return redirect(url_for("suppliers_list"))
        return render_template("supplier_form.html", supplier=s)
    finally:
        db.close()


@app.post("/suppliers/<int:sid>/delete")
@login_required
@require_roles("admin")
def suppliers_delete(sid):
    """Eliminar proveedor"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        name = s.name
        db.delete(s)
        db.commit()
        audit("delete_supplier", "suppliers", {"id": sid, "name": name})
        flash("Proveedor eliminado", "success")
    finally:
        db.close()
    return redirect(url_for("suppliers_list"))


@app.get("/api/supplier/<int:sid>")
@login_required
def api_supplier_detail(sid):
    """API para obtener detalles de proveedor (JSON)"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        data = s.to_dict()
        data['contacts'] = [c.to_dict() for c in s.contacts]
        return jsonify(data)
    finally:
        db.close()


@app.route("/suppliers/<int:sid>/contacts/new", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def contact_new(sid):
    """Crear nuevo contacto para un proveedor"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        if request.method == "POST":
            c = Contact(
                supplier_id=sid,
                name=(request.form.get("name") or "").strip(),
                phone=(request.form.get("phone") or "").strip(),
                email=(request.form.get("email") or "").strip(),
                position=(request.form.get("position") or "").strip(),
                notes=(request.form.get("notes") or "").strip()
            )
            db.add(c)
            db.commit()
            audit("create_contact", "contacts", {"id": c.id, "supplier_id": sid})
            flash("Contacto agregado", "success")
            return redirect(url_for("suppliers_list"))
        return render_template("contact_form.html", supplier=s, contact=None)
    finally:
        db.close()


@app.route("/suppliers/<int:sid>/contacts/<int:cid>/edit", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def contact_edit(sid, cid):
    """Editar contacto"""
    db = SessionLocal()
    try:
        c = db.get(Contact, cid) or abort(404)
        s = db.get(Supplier, sid) or abort(404)
        if request.method == "POST":
            c.name = (request.form.get("name") or "").strip()
            c.phone = (request.form.get("phone") or "").strip()
            c.email = (request.form.get("email") or "").strip()
            c.position = (request.form.get("position") or "").strip()
            c.notes = (request.form.get("notes") or "").strip()
            db.commit()
            audit("update_contact", "contacts", {"id": cid, "supplier_id": sid})
            flash("Contacto actualizado", "success")
            return redirect(url_for("suppliers_list"))
        return render_template("contact_form.html", supplier=s, contact=c)
    finally:
        db.close()


@app.post("/suppliers/<int:sid>/contacts/<int:cid>/delete")
@login_required
@require_roles("admin")
def contact_delete(sid, cid):
    """Eliminar contacto"""
    db = SessionLocal()
    try:
        c = db.get(Contact, cid) or abort(404)
        db.delete(c)
        db.commit()
        audit("delete_contact", "contacts", {"id": cid, "supplier_id": sid})
        flash("Contacto eliminado", "success")
    finally:
        db.close()
    return redirect(url_for("suppliers_list"))


@app.route('/estetica', methods=['GET', 'POST'])
def estetica():
    db = SessionLocal()
    try:
        # Maneja error de dogsize con fallback seguro
        small, medium, large, xl = [], [], [], []
        try:
            small = db.query(Product).filter_by(dogsize='S').all()
            medium = db.query(Product).filter_by(dogsize='M').all()
            large = db.query(Product).filter_by(dogsize='L').all()
            xl = db.query(Product).filter_by(dogsize='XL').all()
        except Exception as e:
            print(f"Error filtrando por dogsize: {e}")
            # Fallback: todos los productos distribuidos
            all_prods = db.query(Product).all()
            # Divide arbitrariamente para no romper el template
            total = len(all_prods)
            small = all_prods[:total//4]
            medium = all_prods[total//4:total//2]
            large = all_prods[total//2:3*total//4]
            xl = all_prods[3*total//4:]
        
        services = db.query(EsteticaService).order_by(EsteticaService.id.desc()).limit(10).all()

        return render_template(
            "estetica.html",
            small=small, medium=medium, large=large, xl=xl,
            services=services,
        )
    finally:
        db.close()



@app.route('/estetica/<servicio>', methods=['GET', 'POST'])
def esteticaform_servicio(servicio):
    nombres_servicios = {
        'banos': 'BAÑOS',
        'banosgarrapaticidas': 'BAÑOS GARRAPATICIDAS',
        'banomedicado': 'BAÑO MEDICADO',
        'cortepelo': 'CORTE DE PELO',
        'deslanado': 'DESLANADO',
        'banodermatologico': 'BAÑO DERMATOLÓGICO',
        'extras': 'EXTRAS',
    }
    nombre_servicio = nombres_servicios.get(servicio, servicio.upper())

    if request.method == 'POST':     
        db = SessionLocal()
        try:
            print(f"DEBUG: propietario={request.form.get('propietarionombre')}, mascota={request.form.get('mascotanombre')}, servicio={request.form.get('servicio')}")
            fecha_str = request.form.get('fecha', '').strip()
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d') if fecha_str else None
        
            # Mapeo explícito: form HTML → modelo (corrige desajustes)
            servicio_obj = EsteticaService(
                fecha=fecha,
                propietarionombre=request.form.get('propietarionombre', '').strip(),  # Form sin guión → modelo con guión
                propietariodireccion=request.form.get('propietariodireccion', '').strip(),
                propietarionumero=request.form.get('propietarionumero', '').strip(),
                mascotanombre=request.form.get('mascotanombre', '').strip(),
                mascotasexo=request.form.get('mascotasexo', '').strip(),
                mascotaedad=request.form.get('mascotaedad', '').strip(),
                mascotaraza=request.form.get('mascotaraza', '').strip(),
                mascotacolor=request.form.get('mascotacolor', '').strip(),
                mascotatamano=float(request.form.get('mascotatamano', 0) or 0),
                observaciones=request.form.get('observaciones', '').strip(),
                servicio=(request.form.get('servicio') or nombre_servicio).strip().upper(),  # Prioriza form, fallback nombre_servicio
                tipocorte=request.form.get('tipocorte', '').strip(),
                precio=float(request.form.get('precio', 0) or 0)  # Manejo seguro
                )
            db.add(servicio_obj) # ← AQUÍ SE AGREGAN
            db.commit() # ← AQUÍ SE GUARDAN
            flash(f'Servicio "{servicio_obj.servicio}" guardado', 'success')
            return redirect(url_for('estetica_servicios'))
        except ValueError as e:
            print(f"Guardando: {servicio_obj.servicio}")
            db.rollback()
            flash(f'Error fecha/precio: {str(e)}', 'error')
        except Exception as e:
            db.rollback()
            flash(f'Error: {str(e)}', 'error')
        finally:
            db.close()


    titulo = nombres_servicios.get(servicio, 'SERVICIO')
    return render_template('estetica_form.html', servicio=servicio, titulo=titulo)


@app.route('/estetica/servicios')
@login_required
def estetica_servicios():  # Renombrado para coincidir con redirects
    db = SessionLocal()
    try:
        services = db.query(EsteticaService).order_by(EsteticaService.created_at.desc()).all()
        return render_template('estetica_servicios.html', services=services)
    finally:
        db.close()

    
# ================== Templates routes end ==================
# Hardware (Windows)
IS_WINDOWS = platform.system() == "Windows"
try:
    import win32print, win32con
except Exception:
    win32print = None
try:
    import wmi as _wmi
except Exception:
    _wmi = None
try:
    from serial.tools import list_ports
except Exception:
    list_ports = None

def hw_detect_printers():
    names, default = [], None
    if IS_WINDOWS and win32print:
        try:
            default = win32print.GetDefaultPrinter()
            for flags in (win32print.PRINTER_ENUM_LOCAL, win32print.PRINTER_ENUM_CONNECTIONS):
                for p in win32print.EnumPrinters(flags):
                    names.append(p[2])
            names = sorted(set(names))
        except Exception:
            pass
    return default, names

def hw_detect_com_ports():
    if list_ports:
        return [p.device for p in list_ports.comports()]
    return []

def hw_list_hid_hint():
    hint = []
    if IS_WINDOWS and _wmi:
        try:
            c = _wmi.WMI()
            for d in c.Win32_PnPEntity(PNPClass="HIDClass"):
                hint.append(d.Name)
        except Exception:
            pass
    return hint

def _send_raw_to_printer(data_bytes: bytes, printer_name: str = None):
    if not (IS_WINDOWS and win32print):
        raise RuntimeError("Impresión RAW solo en Windows con pywin32")
    if not printer_name:
        printer_name = win32print.GetDefaultPrinter()
    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Prueba", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, data_bytes)
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)

@app.route("/admin/hardware", methods=["GET"])
@login_required
@require_roles("admin")
def admin_hardware1():
    default_prn, printers = hw_detect_printers()
    coms = hw_detect_com_ports()
    hid_list = hw_list_hid_hint()
    return render_template("admin_hardware.html",
        default_prn=default_prn, printers=printers,
        coms=coms, hid_list=hid_list, is_windows=IS_WINDOWS)

@app.post("/admin/hardware/print_test")
@login_required
@require_roles("admin")
def hardware_print_test():
    if not (IS_WINDOWS and win32print):
        flash("Solo disponible en Windows con pywin32 instalado", "error")
        return redirect(url_for("admin_hardware"))
    prn = request.form.get("printer") or None
    payload = (
        b"EL ARCA DE CHARLY\r\n"
        b"Prueba de impresora\r\n"
        b"--------------------\r\n"
        b"OK\r\n\r\n"
        b"\x1D\x56\x42\x10"
    )
    try:
        _send_raw_to_printer(payload, prn)
        flash("Impresión enviada","success")
    except Exception as e:
        flash(f"Error imprimiendo: {e}", "error")
    return redirect(url_for("admin_hardware"))

@app.post("/admin/hardware/open_drawer")
@login_required
@require_roles("admin")
def hardware_open_drawer():
    if not (IS_WINDOWS and win32print):
        flash("Solo disponible en Windows con pywin32 instalado", "error")
        return redirect(url_for("admin_hardware"))
    prn = request.form.get("printer") or None
    pulse = b"\x1B\x70\x00\x3C\xFF"  # ESC p m t1 t2
    try:
        _send_raw_to_printer(pulse, prn)
        flash("Pulso enviado (cajón)","success")
    except Exception as e:
        flash(f"Error abriendo cajón: {e}", "error")
    return redirect(url_for("admin_hardware"))

# ================== NUEVAS RUTAS: Suppliers & Contacts ==================
@app.route("/suppliers")
@login_required
def suppliers_list():
    """Lista de proveedores con búsqueda"""
    db = SessionLocal()
    try:
        q = (request.args.get("q") or "").strip()
        base = db.query(Supplier)
        if q:
            base = base.filter(
                (Supplier.name.ilike(f"%{q}%")) | 
                (Supplier.rfc.ilike(f"%{q}%")) |
                (Supplier.email.ilike(f"%{q}%"))
            )
        suppliers = base.order_by(Supplier.name).all()
        return render_template("suppliers_list.html", suppliers=suppliers, q=q)
    finally:
        db.close()


@app.route("/suppliers/new", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def suppliers_new():
    """Crear nuevo proveedor"""
    if request.method == "POST":
        db = SessionLocal()
        try:
            s = Supplier(
                name=(request.form.get("name") or "").strip(),
                rfc=(request.form.get("rfc") or "").strip(),
                email=(request.form.get("email") or "").strip(),
                phone=(request.form.get("phone") or "").strip(),
                address=(request.form.get("address") or "").strip(),
                city=(request.form.get("city") or "").strip(),
                notes=(request.form.get("notes") or "").strip()
            )
            db.add(s)
            db.commit()
            audit("create_supplier", "suppliers", {"id": s.id, "name": s.name})
            flash("Proveedor creado exitosamente", "success")
            return redirect(url_for("suppliers_list"))
        except Exception as e:
            db.rollback()
            flash(f"Error: {e}", "error")
        finally:
            db.close()
    return render_template("supplier_form.html", supplier=None)


@app.route("/suppliers/<int:sid>/edit", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def suppliers_edit(sid):
    """Editar proveedor"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        if request.method == "POST":
            s.name = (request.form.get("name") or "").strip()
            s.rfc = (request.form.get("rfc") or "").strip()
            s.email = (request.form.get("email") or "").strip()
            s.phone = (request.form.get("phone") or "").strip()
            s.address = (request.form.get("address") or "").strip()
            s.city = (request.form.get("city") or "").strip()
            s.notes = (request.form.get("notes") or "").strip()
            db.commit()
            audit("update_supplier", "suppliers", {"id": s.id, "name": s.name})
            flash("Proveedor actualizado", "success")
            return redirect(url_for("suppliers_list"))
        return render_template("supplier_form.html", supplier=s)
    finally:
        db.close()


@app.post("/suppliers/<int:sid>/delete")
@login_required
@require_roles("admin")
def suppliers_delete(sid):
    """Eliminar proveedor"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        name = s.name
        db.delete(s)
        db.commit()
        audit("delete_supplier", "suppliers", {"id": sid, "name": name})
        flash("Proveedor eliminado", "success")
    finally:
        db.close()
    return redirect(url_for("suppliers_list"))


@app.get("/api/supplier/<int:sid>")
@login_required
def api_supplier_detail(sid):
    """API para obtener detalles de proveedor (JSON)"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        data = s.to_dict()
        data['contacts'] = [c.to_dict() for c in s.contacts]
        return jsonify(data)
    finally:
        db.close()


@app.route("/suppliers/<int:sid>/contacts/new", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def contact_new(sid):
    """Crear nuevo contacto para un proveedor"""
    db = SessionLocal()
    try:
        s = db.get(Supplier, sid) or abort(404)
        if request.method == "POST":
            c = Contact(
                supplier_id=sid,
                name=(request.form.get("name") or "").strip(),
                phone=(request.form.get("phone") or "").strip(),
                email=(request.form.get("email") or "").strip(),
                position=(request.form.get("position") or "").strip(),
                notes=(request.form.get("notes") or "").strip()
            )
            db.add(c)
            db.commit()
            audit("create_contact", "contacts", {"id": c.id, "supplier_id": sid})
            flash("Contacto agregado", "success")
            return redirect(url_for("suppliers_list"))
        return render_template("contact_form.html", supplier=s, contact=None)
    finally:
        db.close()


@app.route("/suppliers/<int:sid>/contacts/<int:cid>/edit", methods=["GET", "POST"])
@login_required
@require_roles("admin", "staff")
def contact_edit(sid, cid):
    """Editar contacto"""
    db = SessionLocal()
    try:
        c = db.get(Contact, cid) or abort(404)
        s = db.get(Supplier, sid) or abort(404)
        if request.method == "POST":
            c.name = (request.form.get("name") or "").strip()
            c.phone = (request.form.get("phone") or "").strip()
            c.email = (request.form.get("email") or "").strip()
            c.position = (request.form.get("position") or "").strip()
            c.notes = (request.form.get("notes") or "").strip()
            db.commit()
            audit("update_contact", "contacts", {"id": cid, "supplier_id": sid})
            flash("Contacto actualizado", "success")
            return redirect(url_for("suppliers_list"))
        return render_template("contact_form.html", supplier=s, contact=c)
    finally:
        db.close()


@app.post("/suppliers/<int:sid>/contacts/<int:cid>/delete")
@login_required
@require_roles("admin")
def contact_delete(sid, cid):
    """Eliminar contacto"""
    db = SessionLocal()
    try:
        c = db.get(Contact, cid) or abort(404)
        db.delete(c)
        db.commit()
        audit("delete_contact", "contacts", {"id": cid, "supplier_id": sid})
        flash("Contacto eliminado", "success")
    finally:
        db.close()
    return redirect(url_for("suppliers_list"))


@app.route('/estetica', methods=['GET', 'POST'])
def estetica():
    db = SessionLocal()
    try:
        # Maneja error de dogsize con fallback seguro
        small, medium, large, xl = [], [], [], []
        try:
            small = db.query(Product).filter_by(dogsize='S').all()
            medium = db.query(Product).filter_by(dogsize='M').all()
            large = db.query(Product).filter_by(dogsize='L').all()
            xl = db.query(Product).filter_by(dogsize='XL').all()
        except Exception as e:
            print(f"Error filtrando por dogsize: {e}")
            # Fallback: todos los productos distribuidos
            all_prods = db.query(Product).all()
            # Divide arbitrariamente para no romper el template
            total = len(all_prods)
            small = all_prods[:total//4]
            medium = all_prods[total//4:total//2]
            large = all_prods[total//2:3*total//4]
            xl = all_prods[3*total//4:]
        
        services = db.query(EsteticaService).order_by(EsteticaService.id.desc()).limit(10).all()

        return render_template(
            "estetica.html",
            small=small, medium=medium, large=large, xl=xl,
            services=services,
        )
    finally:
        db.close()



@app.route('/estetica/<servicio>', methods=['GET', 'POST'])
def esteticaform_servicio(servicio):
    nombres_servicios = {
        'banos': 'BAÑOS',
        'banosgarrapaticidas': 'BAÑOS GARRAPATICIDAS',
        'banomedicado': 'BAÑO MEDICADO',
        'cortepelo': 'CORTE DE PELO',
        'deslanado': 'DESLANADO',
        'banodermatologico': 'BAÑO DERMATOLÓGICO',
        'extras': 'EXTRAS',
    }
    nombre_servicio = nombres_servicios.get(servicio, servicio.upper())

    if request.method == 'POST':     
        db = SessionLocal()
        try:
            print(f"DEBUG: propietario={request.form.get('propietarionombre')}, mascota={request.form.get('mascotanombre')}, servicio={request.form.get('servicio')}")
            fecha_str = request.form.get('fecha', '').strip()
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d') if fecha_str else None
        
            # Mapeo explícito: form HTML → modelo (corrige desajustes)
            servicio_obj = EsteticaService(
                fecha=fecha,
                propietarionombre=request.form.get('propietarionombre', '').strip(),  # Form sin guión → modelo con guión
                propietariodireccion=request.form.get('propietariodireccion', '').strip(),
                propietarionumero=request.form.get('propietarionumero', '').strip(),
                mascotanombre=request.form.get('mascotanombre', '').strip(),
                mascotasexo=request.form.get('mascotasexo', '').strip(),
                mascotaedad=request.form.get('mascotaedad', '').strip(),
                mascotaraza=request.form.get('mascotaraza', '').strip(),
                mascotacolor=request.form.get('mascotacolor', '').strip(),
                mascotatamano=float(request.form.get('mascotatamano', 0) or 0),
                observaciones=request.form.get('observaciones', '').strip(),
                servicio=(request.form.get('servicio') or nombre_servicio).strip().upper(),  # Prioriza form, fallback nombre_servicio
                tipocorte=request.form.get('tipocorte', '').strip(),
                precio=float(request.form.get('precio', 0) or 0)  # Manejo seguro
                )
            db.add(servicio_obj) # ← AQUÍ SE AGREGAN
            db.commit() # ← AQUÍ SE GUARDAN
            flash(f'Servicio "{servicio_obj.servicio}" guardado', 'success')
            return redirect(url_for('estetica_servicios'))
        except ValueError as e:
            print(f"Guardando: {servicio_obj.servicio}")
            db.rollback()
            flash(f'Error fecha/precio: {str(e)}', 'error')
        except Exception as e:
            db.rollback()
            flash(f'Error: {str(e)}', 'error')
        finally:
            db.close()


    titulo = nombres_servicios.get(servicio, 'SERVICIO')
    return render_template('estetica_form.html', servicio=servicio, titulo=titulo)


@app.route('/estetica/servicios')
@login_required
def estetica_servicios():  # Renombrado para coincidir con redirects
    db = SessionLocal()
    try:
        services = db.query(EsteticaService).order_by(EsteticaService.created_at.desc()).all()
        return render_template('estetica_servicios.html', services=services)
    finally:
        db.close()

    
# ================== Templates routes end ==================
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
