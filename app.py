from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit
import os
from flask_migrate import Migrate
from utils import fecha_y_hora_colombia, formatear_numero,configurar_socketio, obtener_materiales_bajo_stock, obtener_alertas_almacenista
from werkzeug.exceptions import RequestEntityTooLarge
from sqlalchemy.exc import IntegrityError
# -----------------------------
# IMPORTAR MODELOS Y db
# -----------------------------
from models import db, User, Material, Movimiento, Notificacion

# -----------------------------
# CONFIGURACIÓN DE LA APP
# -----------------------------
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_key')

# SocketIO: inicializar con soporte para eventlet (o gevent si usas gunicorn)
socketio = SocketIO(app, cors_allowed_origins="*")
configurar_socketio(socketio)
# -----------------------------
# REGISTRAR FILTROS JINJA
# -----------------------------
app.jinja_env.filters['fecha_y_hora_colombia'] = fecha_y_hora_colombia
app.jinja_env.filters['formatear_numero'] = formatear_numero

basedir = os.path.abspath(os.path.dirname(__file__))

# Configuración de base de datos
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'civistock.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Carpeta para uploads
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB

# -----------------------------
# INICIALIZAR DB Y MIGRACIONES
# -----------------------------
db.init_app(app)
migrate = Migrate(app, db)

# -----------------------------
# IMPORTAR Y REGISTRAR BLUEPRINTS
# -----------------------------
from admin_routes import admin_bp
from almacenista_routes import almacenista_bp
from ingeniero_routes import ingeniero_bp

app.register_blueprint(admin_bp)
app.register_blueprint(almacenista_bp)
app.register_blueprint(ingeniero_bp)

# -----------------------------
# CONTEXT PROCESSOR
# -----------------------------
@app.context_processor
def inject_user_data():
    contexto = {
        'user': session.get('user'),
        'user_name': session.get('user_name'),
        'user_photo': session.get('user_photo'),
        'user_role': session.get('user_role'),
        'notificaciones': [],
        'usuario_actual': None
    }

    if 'user' in session:
        usuario = User.query.filter_by(username=session['user']).first()
        if usuario:
            contexto['usuario_actual'] = usuario
            contexto['notificaciones_no_leidas'] = Notificacion.query.filter_by(
                usuario_id=usuario.id, leida=False
            ).order_by(Notificacion.fecha.desc()).all()
            contexto['notificaciones'] = Notificacion.query.filter_by(
                usuario_id=usuario.id
            ).order_by(Notificacion.fecha.desc()).limit(10).all()

            # Agrega los materiales con bajo stock
            contexto['materiales_bajo_stock'] = obtener_materiales_bajo_stock()

            # Solo si es almacenista
            if usuario.rol == 'ALMACENISTA':
                contexto.update(obtener_alertas_almacenista())

    return contexto

# -----------------------------
# SOCKETIO - Emitir notificación (global)
# -----------------------------
@app.route('/emitir-notificacion', methods=['POST'])
def emitir_notificacion():
    data = request.get_json()
    mensaje = data.get('mensaje')
    usuario_id = data.get('usuario_id')

    if not mensaje or not usuario_id:
        return jsonify({'error': 'Datos incompletos'}), 400

    noti = Notificacion(mensaje=mensaje, usuario_id=usuario_id, nivel='INFO')
    db.session.add(noti)
    db.session.commit()

    socketio.emit('nueva_notificacion', {
        'mensaje': mensaje,
        'fecha': noti.fecha.strftime("%d/%m/%Y %I:%M %p"),
        'usuario_id': int(usuario_id)
    }, broadcast=True)

    return jsonify({'success': True})

# -----------------------------
# MARCAR NOTIFICACIONES COMO LEÍDAS
# -----------------------------
@app.route('/marcar-notificaciones-leidas', methods=['POST'])
def marcar_notificaciones_leidas():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'No autorizado'}), 401

    notificaciones = Notificacion.query.filter_by(usuario_id=user_id, leida=False).all()
    for n in notificaciones:
        n.leida = True
    db.session.commit()

    return jsonify({'success': True})

# -----------------------------
# CARGAR NOTIFICACIONES RECIENTES (AJAX)
# -----------------------------
@app.route('/notificaciones/recientes')
def notificaciones_recientes():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])

    notificaciones = Notificacion.query.filter_by(
        usuario_id=user_id, leida=False
    ).order_by(Notificacion.fecha.desc()).limit(10).all()

    return jsonify([
        {
            'mensaje': n.mensaje,
            'fecha': n.fecha.strftime("%d/%m/%Y %I:%M %p")
        } for n in notificaciones
    ])

# -----------------------------
# MANEJAR ERRORES DE ARCHIVO
# -----------------------------
@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    flash('⚠️ El archivo es demasiado grande. Máximo 25 MB.', 'danger')
    return redirect(request.referrer or '/')

# -----------------------------
# COMANDOS CLI
# -----------------------------
@app.cli.command('create-db')
def create_db():
    with app.app_context():
        db.create_all()
    print('✅ Base de datos creada correctamente.')

@app.cli.command('create-admin')
def create_admin():
    username = 'admin'
    password = 'admin123'
    nombre = 'Administrador'
    foto = 'admin.png'
    rol = 'ADMIN'

    if User.query.filter_by(username=username).first():
        print('⚠️ El usuario admin ya existe.')
        return

    new_admin = User(username=username, password=password, nombre=nombre, foto=foto, rol=rol)
    db.session.add(new_admin)
    db.session.commit()
    print('✅ Usuario administrador creado.')
    print(f'➡️ Username: {username}, Password: {password}')

# -----------------------------
# RUTAS PRINCIPALES
# -----------------------------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.password == password:
            session['user'] = user.username
            session['user_id'] = user.id
            session['user_name'] = user.nombre
            session['user_photo'] = user.foto
            session['user_role'] = user.rol

            if user.rol.upper() == 'ADMIN':
                return redirect(url_for('admin.dashboard'))
            elif user.rol.upper() == 'ALMACENISTA':
                return redirect(url_for('almacenista.dashboard'))
            elif user.rol.upper() == 'INGENIERO':
                return redirect(url_for('ingeniero.dashboard'))
            else:
                flash(f"Rol desconocido: {user.rol}", 'error')
                return redirect(url_for('home'))
        else:
            flash('Usuario o contraseña incorrectos.', 'error')
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# -----------------------------
# INICIAR APP CON SOCKETIO
# -----------------------------
if __name__ == '__app__':
    socketio.run(app, debug=False)