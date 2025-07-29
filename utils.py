from models import Movimiento, db, Notificacion, Material, User
from sqlalchemy import func
from datetime import datetime
import pytz
from flask_socketio import SocketIO
from datetime import datetime
from flask import session

#para fecha
def fecha_y_hora_colombia(fecha_utc):
    if not fecha_utc:
        return {"fecha": "-", "hora": "-"}
    
    zona_col = pytz.timezone('America/Bogota')

    if fecha_utc.tzinfo is None:
        fecha_utc = pytz.utc.localize(fecha_utc)

    fecha_local = fecha_utc.astimezone(zona_col)

    return {
        "fecha": fecha_local.strftime("%d/%m/%Y"),
        "hora": fecha_local.strftime("%I:%M %p")
    }

#para que los numeros no se vean como decimales si son enteros
def formatear_numero(value):
    try:
        num = float(value)
        if num.is_integer():
            return int(num)
        return num
    except (ValueError, TypeError):
        return value

socketio = None

def configurar_socketio(instance):
    global socketio
    socketio = instance

def emitir_notificacion(tipo_usuario, mensaje, usuario_id=None):
    """Emitir notificación a todos o a un usuario específico (opcional)"""
    if socketio:
        payload = {
            'mensaje': mensaje,
            'fecha': datetime.now().strftime('%d/%m/%Y %I:%M %p'),
            'tipo_usuario': tipo_usuario,
            'usuario_id': usuario_id
        }
        socketio.emit('nueva_notificacion', payload)
        socketio.emit('actualizar-tablas')

# detectar materiales con stock bajo para el TOAST
def obtener_materiales_bajo_stock():
    return Material.query.filter(Material.stock <= Material.stock_minimo).all()


#logica de conteo para las alertas del panel del almacenista
# utils.py

def obtener_alertas_almacenista():
    # --- Solicitudes de retiro pendientes (estado = "PENDIENTE") ---
    pendientes_retiro = Movimiento.query.filter_by(tipo='SOLICITUD', estado='PENDIENTE').count()

    # --- Materiales con stock bajo ---
    stock_bajo_panel = Material.query.filter(Material.stock < Material.stock_minimo).count()

    # --- Última actualización del inventario ---
    ultima_movimiento = Movimiento.query.order_by(Movimiento.fecha.desc()).first()
    ultima_fecha = fecha_y_hora_colombia(ultima_movimiento.fecha) if ultima_movimiento else {"fecha": "-", "hora": "-"}

    # --- Solicitudes de devolucion pendientes ---
    devoluciones_pendientes = Movimiento.query.filter_by(tipo='DEVOLUCION', estado='PENDIENTE').count()

    # --- Devoluciones en revision por ferreteria ---
    devoluciones_en_revision = Movimiento.query.filter(
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        Movimiento.observacion_almacenista.ilike('%estado: En revisión en ferretería%')
    ).count()

    # Devoluciones autorizadas sin revisar aún
    excluir_estados = [
        'estado: En revisión en ferretería',
        'estado: Aprobado por ferretería',
        'estado: Rechazado por ferretería',
        'estado: Movido a materiales sin uso',
        'estado: Retornado a stock'
    ]
    devoluciones_autorizadas_sin_revision = Movimiento.query.filter(
        Movimiento.tipo == 'DEVOLUCION',
        Movimiento.estado == 'AUTORIZADO',
        *[~Movimiento.observacion_almacenista.ilike(f'%{estado}%') for estado in excluir_estados]
    ).count()

    mostrar_alertas = any([
        pendientes_retiro,
        devoluciones_pendientes,
        devoluciones_en_revision,
        devoluciones_autorizadas_sin_revision
    ])

    return {
        'pendientes_retiro': pendientes_retiro,
        'devoluciones_pendientes': devoluciones_pendientes,
        'devoluciones_autorizadas_sin_revision': devoluciones_autorizadas_sin_revision,
        'devoluciones_en_revision': devoluciones_en_revision,
        'stock_bajo_panel':stock_bajo_panel,
        'ultima_fecha':ultima_fecha,
        'mostrar_alertas':mostrar_alertas
    }

def obtener_alertas_ingeniero():

    usuario = User.query.filter_by(username=session.get('user')).first()
    ultimos_movimientos = Movimiento.query.filter_by(solicitado_por_id=usuario.id).order_by(Movimiento.fecha.desc()).limit(5).all()
    return {
        'ultimos_movimientos': ultimos_movimientos
    }    