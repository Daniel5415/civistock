# almacenista_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from datetime import datetime, timezone
from models import db, Material, User, Movimiento, Notificacion
from utils import fecha_y_hora_colombia, emitir_notificacion, obtener_alertas_almacenista
from sqlalchemy import and_, not_, or_
from sqlalchemy.exc import IntegrityError
import os
from collections import defaultdict
almacenista_bp = Blueprint('almacenista', __name__, url_prefix='/almacenista')

# -----------------------------
# Middleware de autenticación
# -----------------------------
def almacenista_required(func):
    def wrapper(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] != 'ALMACENISTA':
            flash('Acceso no autorizado.', 'error')
            return redirect(url_for('home'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
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
# DASHBOARD
# -----------------------------
@almacenista_bp.route('/dashboard')
@almacenista_required
def dashboard():
    sync_user_session()
    datos = obtener_alertas_almacenista()
    return render_template('Almacenista/dashboard_almacenista.html', **datos)

# -----------------------------
# CREAR / LISTAR MATERIALES
# -----------------------------
@almacenista_bp.route('/materiales', methods=['GET', 'POST'])
@almacenista_required
def materiales():
    sync_user_session()

    if request.method == 'POST':
        codigo = request.form.get('codigo')
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        unidad = request.form.get('unidad')
        stock = request.form.get('stock')
        stock_minimo = request.form.get('stock_minimo')

        nuevo = Material(
            codigo=codigo,
            nombre=nombre,
            descripcion=descripcion,
            unidad=unidad,
            stock=float(stock),
            stock_minimo=int(stock_minimo)
        )
        try:
            db.session.add(nuevo)
            db.session.commit()
            flash(' Material creado exitosamente.', 'success')
        except IntegrityError:
            db.session.rollback()
            existente = Material.query.filter_by(codigo=codigo, activo=False).first()
            if existente:
                existente.nombre = nombre
                existente.descripcion = descripcion
                existente.unidad = unidad
                existente.stock = float(stock)
                existente.stock_minimo = int(stock_minimo)
                existente.activo = True
                db.session.commit()
                flash(f' Material creado exitosamente.', 'success')
            else:
                flash(f' Ya existe un material con el código {codigo}.', 'error')

        return redirect(url_for('almacenista.materiales'))

    search_query = request.args.get('q')
    if search_query:
        materiales = Material.query.filter(
            ((Material.codigo.ilike(f'%{search_query}%')) |
            (Material.nombre.ilike(f'%{search_query}%')) |
            (Material.descripcion.ilike(f'%{search_query}%'))) &
            (Material.activo == True)
        ).all()
    else:
        materiales = Material.query.filter(Material.activo == True).all()

    return render_template('Almacenista/nuevo_material.html', materiales=materiales)

# -----------------------------
# EDITAR MATERIAL
# -----------------------------
@almacenista_bp.route('/materiales/editar/<int:id>', methods=['GET', 'POST'])
@almacenista_required
def editar_material(id):
    sync_user_session()
    material = Material.query.get_or_404(id)

    if request.method == 'POST':
        material.codigo = request.form['codigo']
        material.nombre = request.form['nombre']
        material.descripcion = request.form['descripcion']
        material.stock = float(request.form['stock'])
        material.stock_minimo = int(request.form['stock_minimo'])
        db.session.commit()
        flash(' Material actualizado exitosamente.', 'success')
        return redirect(url_for('almacenista.materiales'))

    return render_template('Almacenista/editar_material.html', material=material)

# -----------------------------
# ELIMINAR MATERIAL
# -----------------------------
@almacenista_bp.route('/materiales/eliminar/<int:id>', methods=['POST'])
@almacenista_required
def eliminar_material(id):
    sync_user_session()
    material = Material.query.get_or_404(id)
    material.activo = False
    db.session.commit()
    flash(' Material eliminado exitosamente.', 'warning')
    return redirect(url_for('almacenista.materiales'))

# -----------------------------
# ACTUALIZAR EXISTENCIAS VISUAL
# -----------------------------
@almacenista_bp.route('/actualizar-existencias')
def actualizar_existencias():
    query = request.args.get('q', '').strip()
    
    materiales_q = Material.query.filter(Material.activo == True)
    if query:
        materiales_q = materiales_q.filter(
            db.or_(
                Material.nombre.ilike(f"%{query}%"),
                Material.codigo.ilike(f"%{query}%"),
                Material.descripcion.ilike(f"%{query}%"),
                Material.unidad.ilike(f"%{query}%")
            )
        )
    
    materiales = materiales_q.order_by(Material.nombre).all()

    # Agrupar por unidad, con fallback si no tiene
    grupos = defaultdict(list)
    for m in materiales:
        unidad = m.unidad if (hasattr(m, 'unidad') and m.unidad) else 'Sin unidad'
        grupos[unidad].append(m)

    # Dentro de cada grupo: primero los de stock bajo (stock < stock_minimo), luego por nombre
    for unidad, mats in list(grupos.items()):
        mats.sort(key=lambda m: ((getattr(m, 'stock', 0) >= getattr(m, 'stock_minimo', 0)), (getattr(m, 'nombre', '') or '').lower()))
        grupos[unidad] = mats  # reasignar por si acaso

    return render_template(
        'Almacenista/actualizar_existencias.html',
        grupos=grupos,
        q=query
    )
# -----------------------------
# ACTUALIZAR EXISTENCIA INDIVIDUAL
# -----------------------------
@almacenista_bp.route('/actualizar_existencias/<int:material_id>', methods=['POST'])
@almacenista_required
def actualizar_existencia_individual(material_id):
    """
    Ruta para actualizar individualmente el stock de un material.
    Requiere que el formulario envíe el nuevo stock como campo 'nuevo_stock'.
    """
    nuevo_stock = request.form.get('nuevo_stock')

    material = Material.query.get(material_id)
    if material and material.activo:  # ← validación para materiales activos
        try:
            material.stock = float(nuevo_stock)
            db.session.commit()
            flash(f'Stock actualizado para {material.nombre}', 'success')
        except ValueError:
            flash('Valor inválido para stock. Debe ser un número.', 'error')
    else:
        flash('Material no encontrado o inactivo.', 'error')

    return redirect(url_for('almacenista.actualizar_existencias'))

# -----------------------------
# VER SOLICITUDES PENDIENTES
# -----------------------------
@almacenista_bp.route('/retiros')
@almacenista_required
def retiros_pendientes():
    sync_user_session()
    solicitudes = (
        Movimiento.query
        .join(Material)  # Join con el modelo Material
        .filter(
            Movimiento.tipo == 'SOLICITUD',
            Material.activo == True
        )
        .order_by(Movimiento.fecha.desc())
        .all()
    )

    for solicitud in solicitudes:
        solicitud.fecha_local = fecha_y_hora_colombia(solicitud.fecha)

    return render_template('Almacenista/retiros_pendientes.html', solicitudes=solicitudes)

# -----------------------------
# AUTORIZAR RETIRO
# -----------------------------
@almacenista_bp.route('/retiros/autorizar/<int:id>', methods=['POST'])
@almacenista_required
def autorizar_retiro(id):
    sync_user_session()

    solicitud = Movimiento.query.get_or_404(id)
    material = Material.query.filter_by(id=solicitud.material_id, activo=True).first()  # Aseguramos que el material esté activo
    if not material:
        flash(' Material no encontrado o ya no está disponible.', 'error')
        return redirect(url_for('almacenista.retiros_pendientes'))

    observacion = request.form.get('observacion_almacenista')
    almacenista = db.session.get(User, session.get("user_id"))

    if material.stock < solicitud.cantidad:
        flash(f' Stock insuficiente. Disponible: {material.stock}', 'error')
        return redirect(url_for('almacenista.retiros_pendientes'))
    
    # Actualizaciones
    solicitud.estado = 'AUTORIZADO'
    solicitud.tipo = 'SALIDA'
    solicitud.usuario_id = almacenista.id
    solicitud.observacion_almacenista = observacion
    material.stock -= solicitud.cantidad
    
    ingeniero = solicitud.solicitado_por
    
    if ingeniero:
        mensaje = f" Retiro autorizado: {material.nombre} ({solicitud.cantidad} {material.unidad}) por {almacenista.nombre}"
    db.session.commit()
    
    emitir_notificacion(tipo_usuario='ingeniero', mensaje=mensaje, usuario_id=ingeniero.id)
    flash(' Retiro autorizado correctamente.', 'success')
    return redirect(url_for('almacenista.retiros_pendientes'))


# -----------------------------
# RECHAZAR RETIRO
# -----------------------------
@almacenista_bp.route('/retiros/rechazar/<int:id>', methods=['POST'])
@almacenista_required
def rechazar_retiro(id):
    sync_user_session()
    
    solicitud = Movimiento.query.get_or_404(id)
    material = Material.query.get_or_404(solicitud.material_id)
    almacenista = db.session.get(User, session.get("user_id"))
    ingeniero = db.session.get(User, solicitud.solicitado_por_id)

    observacion = request.form.get('observacion_almacenista')
    
    # Validaciones opcionales (por ejemplo, verificar que esté pendiente, etc.)
    if solicitud.estado != 'PENDIENTE':
        flash(' La solicitud ya fue procesada.', 'warning')
        return redirect(url_for('almacenista.retiros_pendientes'))

    # Actualizar movimiento
    solicitud.usuario_id = almacenista.id
    solicitud.estado = 'RECHAZADO'
    solicitud.tipo = 'SALIDA'
    solicitud.observacion_almacenista = observacion

    # Crear notificación para el ingeniero
    if ingeniero:
        mensaje = f" Solicitud de retiro rechazada: {material.nombre} ({solicitud.cantidad} {material.unidad})."
    db.session.commit()

    emitir_notificacion(tipo_usuario='ingeniero', usuario_id=ingeniero.id, mensaje=mensaje)
    flash(' Solicitud de retiro rechazada.', 'warning')
    return redirect(url_for('almacenista.retiros_pendientes'))

# -----------------------------
# REPORTES MENSUALES
# -----------------------------
from sqlalchemy.orm import joinedload

@almacenista_bp.route('/reportes')
@almacenista_required
def reportes():
    sync_user_session()

    ahora = datetime.now(timezone.utc)
    mes_actual = ahora.month
    año_actual = ahora.year

    movimientos_aprobados = Movimiento.query.join(Material).filter(
        Movimiento.tipo == 'SALIDA',
        Movimiento.estado == 'AUTORIZADO',
        db.extract('month', Movimiento.fecha) == mes_actual,
        db.extract('year', Movimiento.fecha) == año_actual,
        Material.activo == True
    ).options(joinedload(Movimiento.material)).all()

    movimientos_rechazados = Movimiento.query.join(Material).filter(
        Movimiento.tipo == 'SALIDA',
        Movimiento.estado == 'RECHAZADO',
        db.extract('month', Movimiento.fecha) == mes_actual,
        db.extract('year', Movimiento.fecha) == año_actual,
        Material.activo == True
    ).options(joinedload(Movimiento.material)).all()

    devoluciones = Movimiento.query.join(Material).filter(
        Movimiento.tipo == 'DEVOLUCION',
        db.extract('month', Movimiento.fecha) == mes_actual,
        db.extract('year', Movimiento.fecha) == año_actual,
        Material.activo == True
    ).options(joinedload(Movimiento.material)).order_by(Movimiento.fecha.desc()).all()

    ids_de_devoluciones = {d.id for d in devoluciones}
    movimientos_rechazados = [r for r in movimientos_rechazados if r.id not in ids_de_devoluciones]

    for m in movimientos_aprobados + movimientos_rechazados + devoluciones:
        m.fecha_local = fecha_y_hora_colombia(m.fecha)

    return render_template('Almacenista/reportes_mensuales.html',
                            mes=mes_actual,
                            anio=año_actual,
                            aprobados=movimientos_aprobados,
                            rechazados=movimientos_rechazados,
                            devoluciones=devoluciones)

# -----------------------------
# APROBAR / RECHAZAR DEVOLUCIÓN
# -----------------------------
@almacenista_bp.route('/devolucion/<int:id>/aprobar', methods=['POST'])
@almacenista_required
def aprobar_o_rechazar_devolucion(id):
    devolucion = Movimiento.query.get_or_404(id)

    if devolucion.tipo != 'DEVOLUCION' or devolucion.estado != 'PENDIENTE':
        flash('Movimiento inválido o ya procesado.', 'error')
        return redirect(url_for('almacenista.revisar_devoluciones'))

    decision = request.form.get('decision')
    observacion = request.form.get('observacion_almacenista', '').strip()
    almacenista = db.session.get(User, session.get("user_id"))

    # Asignación común
    devolucion.usuario_id = almacenista.id
    devolucion.observacion_almacenista = observacion
    devolucion.visible_en_existencias = True

    if decision == 'aceptar':
        material = devolucion.material
        material.en_devolucion = (material.en_devolucion or 0) + devolucion.cantidad
        devolucion.estado = 'AUTORIZADO'
        mensaje = f" Devolución autorizada: {material.nombre} ({devolucion.cantidad} {material.unidad}). En proceso de validación."
        flash(' Devolución aprobada.', 'success')

    elif decision == 'rechazar':
        if not observacion:
            flash('Debe ingresar una observación al rechazar una devolución.', 'error')
            return redirect(url_for('almacenista.revisar_devoluciones'))

        devolucion.estado = 'RECHAZADO'
        material = devolucion.material  # para el mensaje
        mensaje = f" Devolución rechazada: {material.nombre} ({devolucion.cantidad} {material.unidad}). Contacte al almacenista."
        flash(' Devolución rechazada.', 'warning')
    else:
        flash('Acción no válida.', 'error')
        return redirect(url_for('almacenista.revisar_devoluciones'))

    db.session.commit()

    emitir_notificacion(
        tipo_usuario='ingeniero',
        usuario_id=devolucion.solicitado_por_id,
        mensaje=mensaje
    )
    return redirect(url_for('almacenista.revisar_devoluciones'))

# -----------------------------
# VISTA PARA REVISAR DEVOLUCIONES PENDIENTES
# -----------------------------
@almacenista_bp.route('/revisar_devoluciones')
@almacenista_required
def revisar_devoluciones():
    sync_user_session()
    devoluciones = Movimiento.query.filter_by(tipo='DEVOLUCION', estado='PENDIENTE') \
        .filter(Movimiento.material.has(activo=True)) \
        .order_by(Movimiento.fecha.desc()).all()
    for d in devoluciones:
        d.fecha_local = fecha_y_hora_colombia(d.fecha)
    return render_template('Almacenista/revisar_devoluciones.html', devoluciones=devoluciones)

# -----------------------------
# EXISTENCIAS - Vista principal
# -----------------------------
# Función auxiliar para actualizar estado dentro de la observación
def actualizar_estado_en_observacion(observacion_actual, nuevo_estado):
    if 'estado:' in observacion_actual:
        partes = observacion_actual.split('| estado:')
        base = partes[0].strip()
    else:
        base = observacion_actual.strip()
    return f"{base} | estado: {nuevo_estado}"

@almacenista_bp.route('/existencias')
@almacenista_required
def existencias():
    sync_user_session()

    # Materiales en stock general
    materiales = Material.query.filter_by(activo=True).all()

    # Materiales devueltos visibles en existencias y que no están marcados como "en revisión en ferretería"
    materiales_en_devolucion = Movimiento.query.filter(
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.visible_en_existencias == True,
        not_(Movimiento.observacion_almacenista.ilike('%estado: En revisión en ferretería%'))
    ).order_by(Movimiento.fecha.desc()).all()

    # Materiales enviados a ferretería
    enviados_ferreteria = Movimiento.query.filter(
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.visible_en_existencias == False,
        Movimiento.observacion_almacenista.ilike('%estado: En revisión en ferretería%')
    ).order_by(Movimiento.fecha.desc()).all()

    # Materiales rechazados por ferretería o descartados por el almacenista
    rechazados = Movimiento.query.filter(
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.visible_en_existencias == False,
        or_(
            Movimiento.observacion_almacenista.ilike('%estado: rechazado por ferretería%'),
            Movimiento.observacion_almacenista.ilike('%estado: movido a materiales sin uso%')
        )
    ).order_by(Movimiento.fecha.desc()).all()

    # Materiales aprobados por ferretería
    materiales_aprobados_ferreteria = Movimiento.query.filter(
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.visible_en_existencias == False,
        Movimiento.observacion_almacenista.ilike('%estado: aprobado por ferretería%')
    ).order_by(Movimiento.fecha.desc()).all()

    # Convertir fechas a zona horaria Colombia
    for lista in [materiales_en_devolucion, enviados_ferreteria, rechazados, materiales_aprobados_ferreteria]:
        for mov in lista:
            mov.fecha_local = fecha_y_hora_colombia(mov.fecha)

    # Agregar detalle de estado a los rechazados
    for mov in rechazados:
        if 'rechazado por ferretería' in mov.observacion_almacenista.lower():
            mov.detalle_estado = 'Rechazado por ferretería'
        elif 'movido a materiales sin uso' in mov.observacion_almacenista.lower():
            mov.detalle_estado = 'Material almacenado en descartados'
        else:
            mov.detalle_estado = 'Revisión finalizada'

    return render_template('Almacenista/existencias.html',
                            materiales=materiales,
                            materiales_en_devolucion=materiales_en_devolucion,
                            enviados_ferreteria=enviados_ferreteria,
                            rechazados=rechazados,
                            materiales_aprobados_ferreteria=materiales_aprobados_ferreteria)

# -----------------------------
# Retornar material al stock
# -----------------------------
@almacenista_bp.route('/retornar_a_stock/<int:movimiento_id>', methods=['POST'])
@almacenista_required
def retornar_a_stock(movimiento_id):
    movimiento = Movimiento.query.get_or_404(movimiento_id)
    material = Material.query.get(movimiento.material_id)

    material.stock += movimiento.cantidad
    movimiento.visible_en_existencias = False
    movimiento.activo = False  # ← Marcamos el movimiento como inactivo
    movimiento.observacion_almacenista = actualizar_estado_en_observacion(
        movimiento.observacion_almacenista, "Retornado a stock"
    )

    db.session.commit()

    # Crear mensaje de notificación
    mensaje = f" Devolución de {material.nombre} ({movimiento.cantidad} {material.unidad}) revisada y retornada al stock."
    usuario_id = movimiento.solicitado_por_id

    emitir_notificacion(tipo_usuario='ingeniero', usuario_id=usuario_id, mensaje=mensaje) 
    flash("Material retornado al stock correctamente.", "success")
    return redirect(url_for('almacenista.existencias'))

# -----------------------------
# Enviar material a ferretería
# -----------------------------
@almacenista_bp.route('/enviar_a_ferreteria/<int:movimiento_id>', methods=['POST'])
@almacenista_required
def enviar_a_ferreteria(movimiento_id):
    movimiento = Movimiento.query.get_or_404(movimiento_id)
    material = Material.query.get(movimiento.material_id)

    movimiento.visible_en_existencias = False  # Ya no aparece en la tabla de “en devolución”
    movimiento.activo = True  # Sigue activo para futuras acciones
    movimiento.observacion_almacenista = actualizar_estado_en_observacion(
        movimiento.observacion_almacenista, "En revisión en ferretería"
    )

    mensaje = f" Devolución de {material.nombre} ({movimiento.cantidad} {material.unidad}) enviada a revisión por ferretería."
    usuario_id = movimiento.solicitado_por_id

    db.session.commit()
    emitir_notificacion(tipo_usuario='ingeniero', usuario_id=usuario_id, mensaje=mensaje) 
    flash("Material enviado a revisión en ferretería.", "info")
    return redirect(url_for('almacenista.existencias'))


# -----------------------------
# Aprobar ferretería
# -----------------------------
@almacenista_bp.route('/aprobar_ferreteria/<int:movimiento_id>', methods=['POST'])
@almacenista_required
def aprobar_ferreteria(movimiento_id):
    movimiento = Movimiento.query.get_or_404(movimiento_id)
    material = Material.query.get(movimiento.material_id)

    movimiento.observacion_almacenista = actualizar_estado_en_observacion(
        movimiento.observacion_almacenista, "Aprobado por ferretería"
    )
    movimiento.visible_en_existencias = False
    movimiento.activo = False  # Se da por cerrado

    if material:
        material.stock += movimiento.cantidad

    mensaje = (
        f" Ferretería ha estudiado la devolución de {material.nombre} "
        f"({movimiento.cantidad} {material.unidad}) y ha sido aprobada. "
        f"El material ahora está disponible para su uso en stock."
    )
    usuario_id = movimiento.solicitado_por_id

    db.session.commit()
    emitir_notificacion(tipo_usuario='ingeniero', usuario_id=usuario_id, mensaje=mensaje)
    flash("Material aprobado por ferretería y retornado al stock.", "success")
    return redirect(url_for('almacenista.existencias'))


# -----------------------------
# Rechazar ferretería
# -----------------------------
@almacenista_bp.route('/rechazar_ferreteria/<int:movimiento_id>', methods=['POST'])
@almacenista_required
def rechazar_ferreteria(movimiento_id):
    movimiento = Movimiento.query.get_or_404(movimiento_id)
    material = Material.query.get(movimiento.material_id)

    movimiento.observacion_almacenista = actualizar_estado_en_observacion(
        movimiento.observacion_almacenista, "Rechazado por ferretería"
    )
    movimiento.visible_en_existencias = False
    movimiento.activo = False  # Finaliza el ciclo

    mensaje = (
        f"❌ Ferretería ha revisado la devolución de {material.nombre} "
        f"({movimiento.cantidad} {material.unidad}) y ha sido rechazada. "
        f"El material ha sido marcado como no utilizable y no estará disponible en stock."
    )
    usuario_id = movimiento.solicitado_por_id

    db.session.commit()
    emitir_notificacion(tipo_usuario='ingeniero', usuario_id=usuario_id, mensaje=mensaje)
    flash("Material rechazado por ferretería.", "danger")
    return redirect(url_for('almacenista.existencias'))


# -----------------------------
# Descartar devolución (por pérdida u otra razón)
# -----------------------------
@almacenista_bp.route('/descartar_devolucion/<int:movimiento_id>', methods=['POST'])
@almacenista_required
def descartar_devolucion(movimiento_id):
    movimiento = Movimiento.query.get_or_404(movimiento_id)
    material = Material.query.get(movimiento.material_id)

    movimiento.visible_en_existencias = False
    movimiento.activo = False  # ← IMPORTANTE: lo descartamos completamente
    movimiento.observacion_almacenista = actualizar_estado_en_observacion(
        movimiento.observacion_almacenista, "Movido a materiales sin uso"
    )

    # Notificación al ingeniero
    mensaje = f" La devolución de {material.nombre} ({movimiento.cantidad} {material.unidad}) ha sido revisada. El material ha sido marcado como no utilizable y no estará disponible en el stock."
    usuario_id = movimiento.solicitado_por_id
    db.session.commit()
    
    emitir_notificacion(tipo_usuario='ingeniero', usuario_id=usuario_id, mensaje=mensaje) 
    flash("Material descartado de la vista de existencias.", "warning")
    return redirect(url_for('almacenista.existencias'))

#-------------------------------
# VACIAR NOTIFICACIONES
#-------------------------------
@almacenista_bp.route('/vaciar-notificaciones', methods=['POST'])
def vaciar_notificaciones():
    user_id = session.get('user_id')
    if user_id:
        Notificacion.query.filter_by(usuario_id=user_id).delete()
        db.session.commit()
    return redirect(request.referrer or url_for('almacenista.dashboard'))

#--------------------------
# DEVOLER A PANEL DE ALERTAS
#--------------------------
@almacenista_bp.route('/fragmento-panel-alertas')
def fragmento_panel_alertas():
    datos = obtener_alertas_almacenista()
    return render_template('Almacenista/componentes/_fragmento_panel_alertas.html', **datos)



@almacenista_bp.route('/eliminar-evidencias-temporal')
def eliminar_evidencias_temporal():
    carpeta = os.path.join('static', 'evidencias')
    if os.path.exists(carpeta):
        for archivo in os.listdir(carpeta):
            ruta_archivo = os.path.join(carpeta, archivo)
            try:
                os.remove(ruta_archivo)
            except Exception as e:
                print(f"Error eliminando {archivo}: {e}")
    flash('Evidencias eliminadas correctamente.', 'success')
    return redirect(url_for('almacenista.dashboard'))