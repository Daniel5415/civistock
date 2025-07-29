from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), nullable=False)
    foto = db.Column(db.String(120), nullable=True, default='default.jpg')

    def __repr__(self):
        return f'<User {self.username}>'


class Material(db.Model):
    __tablename__ = 'material'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.String(200))
    stock = db.Column(db.Float, default=0)
    stock_minimo = db.Column(db.Integer, default=0)
    unidad = db.Column(db.String(50))
    en_devolucion = db.Column(db.Float, default=0)

    # Relación con movimientos
    movimientos = db.relationship('Movimiento', backref='material', lazy=True)

    def __repr__(self):
        return f'<Material {self.nombre}>'


class Movimiento(db.Model):
    __tablename__ = 'movimiento'

    id = db.Column(db.Integer, primary_key=True)

    material_id = db.Column(db.Integer, db.ForeignKey('material.id', name='fk_movimiento_material'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    # Usuario que solicita (ingeniero)
    solicitado_por_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_movimiento_solicitante'), nullable=False)
    solicitado_por = db.relationship('User', foreign_keys=[solicitado_por_id], backref='movimientos_solicitados')

    # Usuario que procesa (almacenista)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_movimiento_usuario'))
    usuario = db.relationship('User', foreign_keys=[usuario_id], backref='movimientos_procesados')

    observacion = db.Column(db.Text)
    estado = db.Column(db.String(20), default='PENDIENTE')
    observacion_almacenista = db.Column(db.Text)
    evidencia = db.Column(db.String(200))
    evidencia_almacenista = db.Column(db.String(200))
    visible_en_existencias = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<Movimiento {self.tipo} de {self.cantidad}>'

    
class Notificacion(db.Model):
    __tablename__ = 'notificacion'

    id = db.Column(db.Integer, primary_key=True)
    mensaje = db.Column(db.String(300), nullable=False)
    nivel = db.Column(db.String(10), nullable=False, default='INFO')
    leida = db.Column(db.Boolean, default=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionar con usuario
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_notificacion_usuario'), nullable=False)
    usuario = db.relationship('User', backref='notificaciones')

    def __repr__(self):
        return f'<Notificacion {self.nivel}> - {self.usuario.nombre}>'