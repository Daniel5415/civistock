from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from models import db, User
from functools import wraps
import os
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --------------------------------------
# Decorador para proteger rutas de admin
# --------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] != 'ADMIN':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# -------------------
# DASHBOARD PRINCIPAL
# -------------------
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    usuarios = User.query.all()
    return render_template('admin/dashboard_admin.html', usuarios=usuarios)

# -------------------
# CREAR USUARIO NUEVO
# -------------------
@admin_bp.route('/crear', methods=['GET', 'POST'])
@admin_required
def nuevo_usuario():
    if request.method == 'POST':
        username = request.form['username']
        nombre = request.form['nombre']
        rol = request.form['rol']
        password = request.form['password']

        # Manejo del archivo de foto
        foto_file = request.files.get('foto')
        foto_filename = 'default.jpg'

        if foto_file and foto_file.filename != '':
            filename = secure_filename(foto_file.filename)
            upload_folder = current_app.config['UPLOAD_FOLDER']
            foto_path = os.path.join(upload_folder, filename)
            foto_file.save(foto_path)
            foto_filename = filename

        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'error')
            return redirect(url_for('admin.nuevo_usuario'))

        nuevo_usuario = User(
            username=username,
            nombre=nombre,
            rol=rol,
            password=password,
            foto=foto_filename
        )
        db.session.add(nuevo_usuario)
        db.session.commit()
        flash('Usuario creado correctamente.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/nuevo_usuario.html')

# -------------------
# EDITAR USUARIO
# -------------------
@admin_bp.route('/editar/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def editar_usuario(user_id):
    usuario = User.query.get_or_404(user_id)

    # ⚠️ Bloqueo para evitar edición del admin principal desde aquí
    if usuario.username == 'admin':
        flash('El usuario administrador solo se puede editar desde su perfil.', 'warning')
        return redirect(url_for('admin.listar_usuarios'))

    if request.method == 'POST':
        usuario.nombre = request.form['nombre']
        usuario.rol = request.form['rol']

        new_password = request.form.get('password')
        if new_password:
            usuario.password = new_password

        # Procesar foto nueva
        foto_file = request.files.get('foto')
        if foto_file and foto_file.filename != '':
            filename = secure_filename(foto_file.filename)
            upload_folder = current_app.config['UPLOAD_FOLDER']
            foto_path = os.path.join(upload_folder, filename)
            foto_file.save(foto_path)
            usuario.foto = filename

        db.session.commit()

        # 🟢 NUEVO: actualizar sesión si es el mismo usuario logueado
        if usuario.username == session.get('user'):
            session['user_name'] = usuario.nombre
            session['user_photo'] = usuario.foto

        flash('Usuario actualizado correctamente.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/editar_usuario.html', usuario=usuario)

# -------------------
# LISTAR USUARIOS
# -------------------
@admin_bp.route('/usuarios')
@admin_required
def listar_usuarios():
    usuarios = User.query.all()
    return render_template('admin/listar_usuarios.html', usuarios=usuarios)

# -------------------
# ELIMINAR USUARIO
# -------------------
@admin_bp.route('/eliminar/<int:user_id>', methods=['POST'])
@admin_required
def eliminar_usuario(user_id):
    usuario = User.query.get_or_404(user_id)

    # ⚠️ Bloqueo para evitar borrado del admin principal
    if usuario.username == 'admin':
        flash('No puedes eliminar al usuario administrador.', 'error')
        return redirect(url_for('admin.listar_usuarios'))

    db.session.delete(usuario)
    db.session.commit()
    flash('Usuario eliminado correctamente.', 'success')
    return redirect(url_for('admin.dashboard'))

# -------------------
# PERFIL DEL ADMIN
# -------------------
@admin_bp.route('/perfil', methods=['GET', 'POST'])
@admin_required
def perfil():
    usuario = User.query.filter_by(username=session['user']).first_or_404()

    if request.method == 'POST':
        usuario.nombre = request.form['nombre']

        new_password = request.form.get('password')
        if new_password:
            usuario.password = new_password

        # Manejo de foto actualizada
        foto_file = request.files.get('foto')
        if foto_file and foto_file.filename != '':
            filename = secure_filename(foto_file.filename)
            upload_folder = current_app.config['UPLOAD_FOLDER']
            foto_path = os.path.join(upload_folder, filename)
            foto_file.save(foto_path)
            usuario.foto = filename

        db.session.commit()

        # Actualizar sesión para reflejar cambios
        session['user_name'] = usuario.nombre
        session['user_photo'] = usuario.foto

        flash('Perfil actualizado correctamente.', 'success')
        return redirect(url_for('admin.perfil'))

    return render_template('admin/perfil.html', usuario=usuario)
