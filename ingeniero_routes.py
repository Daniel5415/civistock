# ingeniero_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from models import db, User, Material, Movimiento,Notificacion
from datetime import datetime, timezone
from functools import wraps
from utils import fecha_y_hora_colombia, emitir_notificacion, obtener_alertas_ingeniero
import os
from werkzeug.utils import secure_filename
from weasyprint import HTML
from sqlalchemy import func
import requests

ingeniero_bp = Blueprint('ingeniero', __name__, url_prefix='/ingeniero')

UPLOAD_FOLDER = os.path.join('static', 'evidencias')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -----------------------------
# Middleware de autenticación
# -----------------------------
def ingeniero_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] != 'INGENIERO':
            flash('Acceso no autorizado.', 'error')
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

# -----------------------------
# Sincronizar sesión
# -----------------------------
def sync_user_session():
    user = User.query.filter_by(username=session.get('user')).first()
    if user:
        session['user_name'] = user.nombre
        session['user_photo'] = user.foto
        session['user_id'] = user.id


# -----------------------------
# Dashboard
# -----------------------------
@ingeniero_bp.route('/dashboard')
@ingeniero_required
def dashboard():
    sync_user_session()
    usuario = User.query.filter_by(username=session.get('user')).first()

    ultimos_movimientos = (
        Movimiento.query
        .join(Material)
        .filter(Movimiento.solicitado_por_id == usuario.id, Material.activo == True)
        .order_by(Movimiento.fecha.desc())
        .limit(5)
        .all()
    )

    return render_template(
        'Ingeniero/dashboard_ingeniero.html',
        ultimos_movimientos=ultimos_movimientos,
        fecha_y_hora_colombia=fecha_y_hora_colombia
    )


# -----------------------------
# Ver existencias
# -----------------------------
@ingeniero_bp.route('/existencias')
@ingeniero_required
def existencias():
    sync_user_session()
    materiales = Material.query.filter_by(activo=True).all()
    return render_template('Ingeniero/existencias_ingeniero.html', materiales=materiales)

# -----------------------------
# Solicitar retiro
# -----------------------------
@ingeniero_bp.route('/solicitar-retiro', methods=['GET', 'POST'])
@ingeniero_required
def solicitar_retiro():
    sync_user_session()
    materiales = Material.query.filter_by(activo=True).all()

    if request.method == 'POST':
        material_id = request.form.get('material_id')
        cantidad = request.form.get('cantidad')
        observacion = request.form.get('observacion') or None

        usuario = User.query.filter_by(username=session.get('user')).first()
        if not usuario:
            flash('Usuario no encontrado.', 'error')
            return redirect(url_for('ingeniero.solicitar_retiro'))

        movimiento = Movimiento(
            tipo='SOLICITUD',
            material_id=int(material_id),
            cantidad=float(cantidad),
            solicitado_por_id=usuario.id,
            usuario_id=None,
            observacion=observacion
        )

        db.session.add(movimiento)
        db.session.commit()

        almacenista = User.query.filter_by(rol='ALMACENISTA').first()
        material = Material.query.get(int(material_id))

        if almacenista and material:
            mensaje = (
                f" Nueva solicitud de retiro: {material.nombre} "
                f"({cantidad} {material.unidad}) solicitada por {usuario.nombre}."
            )
            if observacion:
                mensaje += f"\n📝 Observación: {observacion}"
            emitir_notificacion(tipo_usuario='almacenista', usuario_id=almacenista.id, mensaje=mensaje)

        flash(' Solicitud de retiro enviada.', 'success')
        return redirect(url_for('ingeniero.solicitar_retiro'))

    return render_template('Ingeniero/solicitar_retiro.html', materiales=materiales)

# -----------------------------
# Historial de retiros
# -----------------------------
@ingeniero_bp.route('/historial-retiros')
@ingeniero_required
def historial_retiros():
    sync_user_session()
    usuario = User.query.filter_by(username=session.get('user')).first()

    if not usuario:
        flash('Usuario no encontrado.', 'error')
        return redirect(url_for('ingeniero.dashboard'))

    movimientos = (
        Movimiento.query
        .join(Material)  # Unimos con la tabla Material
        .filter(
            Movimiento.solicitado_por_id == usuario.id,
            Material.activo == True  # Solo materiales activos
        )
        .order_by(Movimiento.fecha.desc())
        .all()
    )

    for mov in movimientos:
        mov.fecha_local = fecha_y_hora_colombia(mov.fecha)

    return render_template('Ingeniero/historial_retiros.html', movimientos=movimientos)

# -----------------------------
# Reportes de obra
# -----------------------------
@ingeniero_bp.route('/reportes')
@ingeniero_required
def reportes():
    sync_user_session()
    usuario = User.query.filter_by(username=session.get('user')).first()

    if not usuario:
        flash('Usuario no encontrado.', 'error')
        return redirect(url_for('ingeniero.dashboard'))

    aprobados = (
        Movimiento.query
        .join(Material)
        .filter(
            Movimiento.solicitado_por_id == usuario.id,
            Movimiento.tipo == 'SALIDA',
            Movimiento.estado == 'AUTORIZADO',
            Material.activo == True
        )
        .order_by(Movimiento.fecha.desc())
        .all()
    )

    rechazados = (
        Movimiento.query
        .join(Material)
        .filter(
            Movimiento.solicitado_por_id == usuario.id,
            Movimiento.tipo == 'SALIDA',
            Movimiento.estado == 'RECHAZADO',
            Material.activo == True
        )
        .order_by(Movimiento.fecha.desc())
        .all()
    )

    devoluciones = (
        Movimiento.query
        .join(Material)
        .filter(
            Movimiento.solicitado_por_id == usuario.id,
            Movimiento.tipo == 'DEVOLUCION',
            Material.activo == True
        )
        .order_by(Movimiento.fecha.desc())
        .all()
    )

    for mov in aprobados + rechazados + devoluciones:
        mov.fecha_local = fecha_y_hora_colombia(mov.fecha)

    return render_template(
        'Ingeniero/reportes_ingeniero.html',
        aprobados=aprobados,
        rechazados=rechazados,
        devoluciones=devoluciones
    )

# -----------------------------
# Borrar historial
# -----------------------------
@ingeniero_bp.route('/borrar-historial-retiros')
@ingeniero_required
def borrar_historial_retiros():
    usuario = User.query.filter_by(username=session.get('user')).first()

    if not usuario:
        flash('Usuario no encontrado.', 'error')
        return redirect(url_for('login'))

    Movimiento.query.filter(
        Movimiento.solicitado_por_id == usuario.id,
        Movimiento.tipo.in_(['SALIDA', 'SOLICITUD', 'DEVOLUCION'])
    ).delete(synchronize_session=False)

    db.session.commit()
    flash('Historial de retiros, solicitudes y devoluciones borrado.', 'success')
    return redirect(url_for('ingeniero.historial_retiros'))

# -----------------------------
# Historial de devoluciones
# -----------------------------
@ingeniero_bp.route('/historial-devoluciones')
@ingeniero_required
def historial_devoluciones():
    sync_user_session()
    usuario = User.query.filter_by(username=session.get('user')).first()

    if not usuario:
        flash('Usuario no encontrado.', 'error')
        return redirect(url_for('ingeniero.dashboard'))

    devoluciones = (
        Movimiento.query
        .join(Material)
        .filter(
            Movimiento.solicitado_por_id == usuario.id,
            Movimiento.tipo == 'DEVOLUCION',
            Material.activo == True
        )
        .order_by(Movimiento.fecha.desc())
        .all()
    )

    for dev in devoluciones:
        dev.fecha_local = fecha_y_hora_colombia(dev.fecha)

    return render_template('historial_devoluciones.html', devoluciones=devoluciones)

# -----------------------------
# Realizar devolución con evidencia
# -----------------------------
@ingeniero_bp.route('/realizar-devolucion', methods=['GET', 'POST'])
def realizar_devolucion():
    usuario_id = session.get('user_id')

    if request.method == 'GET':
        materiales = Material.query.filter_by(activo=True).all()  #  Solo materiales activos

        for material in materiales:
            total_retirado = db.session.query(func.sum(Movimiento.cantidad)).filter(
                Movimiento.material_id == material.id,
                Movimiento.tipo == 'SALIDA',
                Movimiento.estado == 'AUTORIZADO',
                Movimiento.solicitado_por_id == usuario_id
            ).scalar() or 0

            total_devuelto = db.session.query(func.sum(Movimiento.cantidad)).filter(
                Movimiento.material_id == material.id,
                Movimiento.tipo == 'DEVOLUCION',
                Movimiento.estado == 'AUTORIZADO',
                Movimiento.solicitado_por_id == usuario_id
            ).scalar() or 0

            total_dev_pendientes = db.session.query(func.sum(Movimiento.cantidad)).filter(
                Movimiento.material_id == material.id,
                Movimiento.tipo == 'DEVOLUCION',
                Movimiento.estado == 'PENDIENTE',
                Movimiento.solicitado_por_id == usuario_id
            ).scalar() or 0

            material.total_retirado = total_retirado
            material.disponible_para_devolver = max(total_retirado - (total_devuelto + total_dev_pendientes), 0)

        return render_template('Ingeniero/realizar_devolucion.html', materiales=materiales)
    
    # POST
    material_id = request.form.get('material_id')
    try:
        cantidad = float(request.form.get('cantidad', 0).strip())
    except ValueError:
        flash('⚠ Cantidad inválida.', 'error')
        return redirect(request.referrer or url_for('ingeniero.realizar_devolucion'))
    observacion = request.form.get('observacion', '').strip()
    evidencia = request.files.get('archivo')
    usuario_id = session.get('user_id')

    material = Material.query.get_or_404(material_id)

    total_retirado = db.session.query(func.sum(Movimiento.cantidad)).filter(
        Movimiento.material_id == material_id,
        Movimiento.tipo == 'SALIDA',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.solicitado_por_id == usuario_id
    ).scalar() or 0

    total_devuelto = db.session.query(func.sum(Movimiento.cantidad)).filter(
        Movimiento.material_id == material_id,
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.solicitado_por_id == usuario_id
    ).scalar() or 0

    disponible_para_devolver = total_retirado - total_devuelto

    if total_retirado == 0:
        flash('⚠ No has retirado este material, la devolución será evaluada por el almacenista.', 'warning')
    elif cantidad > disponible_para_devolver:
        if not observacion:
            flash(f"⚠ Estás devolviendo más de lo permitido ({disponible_para_devolver}). Debes justificarlo en la observación.", "error")
        else:
            flash(f"⚠ Estás devolviendo más de lo disponible ({disponible_para_devolver}). Tu solicitud fue registrada y será revisada.", "warning")

    nombre_archivo = None
    if evidencia and evidencia.filename:
        filename = secure_filename(evidencia.filename)
        datos_fecha = fecha_y_hora_colombia(datetime.now(timezone.utc))
        timestamp = f"{datos_fecha['fecha'].replace('/', '-')}_{datos_fecha['hora'].replace(':', '-').replace(' ', '')}"
        nombre_archivo = f"{timestamp}_{filename}"
        ruta_evidencia = os.path.join('static', 'evidencias', nombre_archivo)
        evidencia.save(ruta_evidencia)

    movimiento = Movimiento(
        tipo='DEVOLUCION',
        cantidad=cantidad,
        material_id=material_id,
        estado='PENDIENTE',
        observacion=observacion,
        usuario_id=usuario_id,
        solicitado_por_id=usuario_id,
        evidencia=nombre_archivo
    )
    db.session.add(movimiento)
    db.session.commit()
    usuario = db.session.get(User, usuario_id)
    almacenista = User.query.filter_by(rol='ALMACENISTA').first()

    if almacenista:
        mensaje = (
            f"↩ Nueva solicitud de devolución: {material.nombre} "
            f"({cantidad} {material.unidad}) solicitada por {usuario.nombre}."
        )
        if observacion:
            mensaje += f"\n Observación: {observacion}"
        try:
            emitir_notificacion(tipo_usuario='almacenista', usuario_id=almacenista.id, mensaje=mensaje)

        except Exception as e:
            print(f"Error al emitir notificación: {e}")

    flash(' Solicitud de devolución enviada correctamente.', 'success')
    return redirect(url_for('ingeniero.reportes'))
# -----------------------------
# Generar reporte en pdf
# -----------------------------
ACTIVAR_PDF_INGENIERO = True  # cambiar a False cuando quiera ocultarse

@ingeniero_bp.route('/generar-pdf')
@ingeniero_required
def generar_pdf():
    if not ACTIVAR_PDF_INGENIERO:
        return "Esta funcionalidad está temporalmente inactiva.", 404

    from datetime import datetime
    from collections import Counter
    import base64
    import os
    from utils import fecha_y_hora_colombia

    def convertir_a_base64(ruta):
        ruta_completa = os.path.join('static', ruta)
        try:
            with open(ruta_completa, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            print(f"Error al convertir {ruta} a base64:", e)
            return None

    sync_user_session()
    usuario = User.query.filter_by(username=session.get('user')).first()

    # Obtener movimientos
    aprobados = Movimiento.query.filter_by(
        solicitado_por_id=usuario.id,
        tipo='SALIDA',
        estado='AUTORIZADO'
    ).order_by(Movimiento.fecha.desc()).all()

    rechazados = Movimiento.query.filter(
        Movimiento.solicitado_por_id == usuario.id,
        Movimiento.estado == 'RECHAZADO',
        Movimiento.tipo.in_(['SOLICITUD', 'SALIDA'])
    ).order_by(Movimiento.fecha.desc()).all()

    devoluciones = Movimiento.query.filter_by(
        solicitado_por_id=usuario.id,
        tipo='DEVOLUCION'
    ).order_by(Movimiento.fecha.desc()).all()

    for mov in aprobados + rechazados + devoluciones:
        mov.fecha_colombia = fecha_y_hora_colombia(mov.fecha)
        if mov.evidencia:
            mov.evidencia_base64 = convertir_a_base64(os.path.join('evidencias', mov.evidencia))
        else:
            mov.evidencia_base64 = None

    # Estadísticas
    materiales = [mov.material.nombre for mov in aprobados]
    material_mas_retirado = Counter(materiales).most_common(1)[0][0] if materiales else None

    # Fecha y hora actual con formato colombiano
    ahora_utc = datetime.utcnow()
    fecha_hora_actual = fecha_y_hora_colombia(ahora_utc)

    # Obtener mes en español manualmente
    meses_es = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]
    mes_actual = meses_es[datetime.now().month - 1]
    anio_actual = datetime.now().year

    # Logo en base64
    logo_base64 = convertir_a_base64("civistockresponsive.png")
    logo_portada_base64 = convertir_a_base64("logo_civistock.png")

    rendered = render_template(
        'Ingeniero/pdf_reporte_ingeniero.html',
        usuario=usuario,
        movimientos_aprobados=aprobados,
        movimientos_rechazados=rechazados,
        movimientos_devoluciones=devoluciones,
        total_aprobados=len(aprobados),
        total_rechazados=len(rechazados),
        total_devoluciones=len(devoluciones),
        material_mas_retirado=material_mas_retirado,
        mes_actual=mes_actual,
        anio_actual=anio_actual,
        fecha_hora_actual=fecha_hora_actual,
        logo_base64=logo_base64,
        logo_portada_base64=logo_portada_base64
    )

    pdf = HTML(string=rendered).write_pdf()

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=reporte_{usuario.nombre}.pdf'
    return response

#-------------------------------
# VACIAR NOTIFICACIONES
#-------------------------------
@ingeniero_bp.route('/vaciar-notificaciones', methods=['POST'])
def vaciar_notificaciones():
    user_id = session.get('user_id')
    if user_id:
        Notificacion.query.filter_by(usuario_id=user_id).delete()
        db.session.commit()
    return redirect(request.referrer or url_for('ingeniero.dashboard'))

#-------------------------------
# Obtener alertas ingeniero
#-------------------------------
@ingeniero_bp.route('/fragmento-panel-movimientos')
def fragmento_panel_ingeniero():
    datos = obtener_alertas_ingeniero()
    return render_template('Ingeniero/componentes/_fragmento_panel_movimientos_ing.html', **datos,fecha_y_hora_colombia=fecha_y_hora_colombia)

