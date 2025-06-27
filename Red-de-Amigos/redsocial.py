import networkx as nx
import bcrypt
import json
import os
from datetime import datetime
from itsdangerous import URLSafeTimedSerializer

class Foto:
    def __init__(self, filename, descripcion, autor, comentarios=None, likes=None):
        self.filename = filename
        self.descripcion = descripcion
        self.autor = autor
        self.comentarios = comentarios or []  # Ahora será lista de dicts
        self.likes = set(likes) if likes else set()  # conjunto de usernames

    def to_dict(self):
        return {
            "filename": self.filename,
            "descripcion": self.descripcion,
            "autor": self.autor,
            "comentarios": self.comentarios,
            "likes": list(self.likes)
        }

    @staticmethod
    def from_dict(data):
        return Foto(
            data["filename"],
            data["descripcion"],
            data["autor"],
            data.get("comentarios", []),
            data.get("likes", [])
        )

class Usuario:
    def __init__(self, username, password, datos_personales, intereses, privacidad,
                 solicitudes_enviadas=None, solicitudes_recibidas=None, avatar=None,
                 verificado=False):
        # Inicializa un usuario con sus datos
        self.username = username
        self.password_hash = self.hashear_contrasena(password) if isinstance(password, str) else password
        self.datos_personales = datos_personales  # debe incluir 'email'
        self.intereses = intereses
        self.privacidad = privacidad
        self.solicitudes_enviadas = solicitudes_enviadas or []
        self.solicitudes_recibidas = solicitudes_recibidas or []
        self.avatar = avatar or "default.png"
        self.fotos = []  # lista de objetos Foto
        self.mensajes_recibidos = []  # lista de Mensaje
        self.mensajes_enviados = []   # lista de Mensaje
        self.verificado = verificado

    def hashear_contrasena(self, password):
        # Hashea la contraseña para almacenarla de forma segura
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    def verificar_contrasena(self, password):
        # Verifica si la contraseña ingresada coincide con el hash almacenado
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash)

    def to_dict(self):
        return {
            "username": self.username,
            "password_hash": self.password_hash.decode('utf-8') if isinstance(self.password_hash, bytes) else self.password_hash,
            "datos_personales": self.datos_personales,
            "intereses": self.intereses,
            "privacidad": self.privacidad,
            "solicitudes_enviadas": self.solicitudes_enviadas,
            "solicitudes_recibidas": self.solicitudes_recibidas,
            "avatar": self.avatar,
            "fotos": [foto.to_dict() for foto in self.fotos],
            "verificado": self.verificado
        }

    @staticmethod
    def from_dict(data):
        obj = Usuario(
            data["username"],
            data["password_hash"].encode('utf-8') if isinstance(data["password_hash"], str) else data["password_hash"],
            data["datos_personales"],
            data["intereses"],
            data["privacidad"],
            data.get("solicitudes_enviadas", []),
            data.get("solicitudes_recibidas", []),
            data.get("avatar", "default.png")
        )
        obj.fotos = [Foto.from_dict(f) for f in data.get("fotos", [])]
        obj.verificado = data.get("verificado", False)
        return obj

    def calcular_edad(self):
        # Si hay campo 'edad', úsalo; si hay 'fecha_nacimiento', calcula la edad
        if "edad" in self.datos_personales:
            return self.datos_personales["edad"]
        elif "fecha_nacimiento" in self.datos_personales:
            nacimiento = datetime.strptime(self.datos_personales["fecha_nacimiento"], "%Y-%m-%d")
            hoy = datetime.today()
            return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
        return "Desconocida"

class RedSocial:
    def __init__(self):
        # Inicializa la red social como un grafo
        self.grafo = nx.Graph()
        self.cargar_datos()

    def registrar_usuario(self, usuario: Usuario):
        # Registra un nuevo usuario en el grafo
        if usuario.username in self.grafo:
            raise ValueError("Nombre de usuario ya existe")
        self.grafo.add_node(usuario.username, datos=usuario)
        self.guardar_datos()

    def conectar_usuarios(self, user1: str, user2: str):
        # Conecta dos usuarios como amigos
        self.grafo.add_edge(user1, user2)
        self.guardar_datos()

    def obtener_usuario(self, username):
        return self.grafo.nodes[username]['datos']

    def autenticar_usuario(self, username: str, password: str) -> bool:
        # Verifica si el usuario y contraseña son correctos
        if username not in self.grafo:
            return False
        usuario = self.obtener_usuario(username)
        return usuario.verificar_contrasena(password)

    def listar_usuarios(self):
        # Devuelve la lista de todos los usuarios
        return list(self.grafo.nodes)

    def recomendar_amigos(self, username: str, top_n: int = 5):
        # Recomienda amigos basados en intereses similares
        usuario = self.obtener_usuario(username)
        similitudes = []

        for other_username in self.grafo.nodes():
            # No recomienda a sí mismo ni a quienes ya son amigos
            if other_username == username or self.grafo.has_edge(username, other_username):
                continue
            other_user = self.obtener_usuario(other_username)
            score = self.calcular_similitud(usuario, other_user)
            similitudes.append((other_username, score))

        # Ordena por mayor similitud y devuelve los mejores
        similitudes.sort(key=lambda x: x[1], reverse=True)
        return [user for user, _ in similitudes[:top_n]]

    def calcular_similitud(self, u1: Usuario, u2: Usuario) -> float:
        # Calcula la similitud entre dos usuarios según sus intereses
        intereses_u1 = set(u1.intereses.keys())
        intereses_u2 = set(u2.intereses.keys())
        interseccion = intereses_u1.intersection(intereses_u2)
        if not interseccion:
            return 0.0
        score = 0
        for interes in interseccion:
            if u1.intereses[interes].lower() == u2.intereses[interes].lower():
                score += 2
            else:
                score += 1
        return score / (len(intereses_u1.union(intereses_u2)))

    def guardar_datos(self):
        # Guarda todos los usuarios en un archivo JSON
        data = {}
        for node in self.grafo.nodes():
            usuario = self.grafo.nodes[node]['datos']
            data[node] = usuario.to_dict()
        edges = list(self.grafo.edges())
        with open('usuarios.json', 'w') as f:
            json.dump({"usuarios": data, "amistades": edges}, f, indent=4)

    def cargar_datos(self):
        # Carga los usuarios desde el archivo JSON si existe
        if not os.path.exists('usuarios.json'):
            return
        with open('usuarios.json', 'r') as f:
            data = json.load(f)
        usuarios = data.get("usuarios", data)  # Soporta formato viejo y nuevo
        for username, datos in usuarios.items():
            usuario = Usuario.from_dict(datos)
            self.grafo.add_node(username, datos=usuario)
        # Cargar amistades si existen
        for u1, u2 in data.get("amistades", []):
            if u1 in self.grafo and u2 in self.grafo:
                self.grafo.add_edge(u1, u2)
        # Actualizar comentarios de fotos para todos los usuarios
        for username in self.grafo.nodes():
            usuario = self.grafo.nodes[username]['datos']
            for foto in usuario.fotos:
                nuevos_comentarios = []
                for idx, c in enumerate(foto.comentarios, 1):
                    if isinstance(c, dict):
                        nuevos_comentarios.append(c)
                    elif isinstance(c, tuple) and len(c) == 2:
                        nuevos_comentarios.append({
                            "id": idx,
                            "usuario": c[0],
                            "texto": c[1]
                        })
                foto.comentarios = nuevos_comentarios

    def obtener_usuario_por_email(self, email):
        for username in self.grafo.nodes:
            usuario = self.grafo.nodes[username]['datos']
            if usuario.datos_personales.get('email') == email:
                return usuario
        return None

class Mensaje:
    def __init__(self, emisor, receptor, texto, fecha=None):
        self.emisor = emisor
        self.receptor = receptor
        self.texto = texto
        self.fecha = fecha or datetime.now().strftime("%Y-%m-%d %H:%M")
    
    def to_dict(self):
        return {
            "emisor": self.emisor,
            "receptor": self.receptor,
            "texto": self.texto,
            "fecha": self.fecha
        }



