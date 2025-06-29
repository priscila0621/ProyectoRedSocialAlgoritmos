from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from redsocial import RedSocial, Usuario, Foto, Mensaje  # Asegúrate de importar la función
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import os
import datetime

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__)
app.secret_key = 'clave_secreta_segura'
red = RedSocial()

# Configuración de Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'entrelazadosapp@gmail.com'
app.config['MAIL_PASSWORD'] = 'oqkpncnrjjqkjmmu'
mail = Mail(app)

@app.context_processor
def inject_red():
    return dict(red=red)

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('feed'))
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        # Obtén los datos del formulario
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        nombre = request.form['nombre']
        email = request.form['email']
        ciudad = request.form.get('ciudad', '')
        descripcion = request.form.get('descripcion', '')
        intereses_seleccionados = request.form.getlist('intereses')
        intereses = {}
        for interes in intereses_seleccionados:
            detalle = request.form.get(f'detalle_{interes}', '')
            intereses[interes] = detalle
        privacidad = {} # Llena esto según tu lógica
        fecha_nacimiento = request.form['fecha_nacimiento']
        try:
            nacimiento = datetime.datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        except ValueError:
            flash("Fecha de nacimiento inválida.", "danger")
            return render_template('register.html')

        hoy = datetime.date.today()
        edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
        if edad < 16:
            flash("Debes tener al menos 16 años para registrarte.", "danger")
            return render_template('register.html')

        fecha_registro = datetime.date.today().isoformat()

        if password != confirm_password:
            flash("Las contraseñas no coinciden.", "danger")
            return render_template('register.html')

        datos_personales = {
            "nombre": nombre,
            "fecha_nacimiento": fecha_nacimiento,
            "email": email,
            "ciudad": ciudad,
            "descripcion": descripcion,
            "fecha_registro": fecha_registro
        }

        usuario = Usuario(username, password, datos_personales, intereses, privacidad)
        try:
            red.registrar_usuario(usuario)
            # --- Aquí va el envío del correo de verificación ---
            token = generar_token(email)
            enlace = url_for('confirmar_correo', token=token, _external=True)
            msg = Message('Confirma tu correo', sender='tu-correo', recipients=[email])
            msg.body = f'Por favor confirma tu correo haciendo clic en este enlace: {enlace}'
            mail.send(msg)
            flash("Te enviamos un correo para confirmar tu cuenta.", "info")
            return redirect(url_for('login'))
        except ValueError:
            flash("El usuario ya existe.", "danger")
            return render_template('register.html')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if red.autenticar_usuario(username, password):
            usuario = red.obtener_usuario(username)
            if not getattr(usuario, "verificado", False):
                flash("Debes confirmar tu correo antes de iniciar sesión.", "warning")
                return render_template('login.html', ocultar_nav=True, username=username, mostrar_reenviar=True)
            session['username'] = username
            return redirect(url_for('feed'))
        flash("Usuario o contraseña incorrectos.", "danger")
        return render_template('login.html', ocultar_nav=True, username=username)
    return render_template('login.html', ocultar_nav=True)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/feed')
def feed():
    usuario = red.obtener_usuario(session['username'])
    amigos = list(red.grafo.neighbors(usuario.username))
    usuarios_feed = amigos  # <-- Solo amigos, no te incluyas a ti mismo
    publicaciones = []
    for u in usuarios_feed:
        amigo = red.obtener_usuario(u)
        for foto in getattr(amigo, 'fotos', []):
            publicaciones.append({
                'usuario': amigo,
                'foto': foto
            })
    publicaciones.sort(key=lambda x: getattr(x['foto'], 'fecha', ''), reverse=True)

    # --- Conversaciones para la mensajería lateral ---
    conversaciones_usernames = set()
    if hasattr(usuario, 'mensajes_enviados'):
        conversaciones_usernames.update(
            m['receptor'] if isinstance(m, dict) else m.receptor
            for m in usuario.mensajes_enviados
        )
    if hasattr(usuario, 'mensajes_recibidos'):
        conversaciones_usernames.update(
            m['emisor'] if isinstance(m, dict) else m.emisor
            for m in usuario.mensajes_recibidos
        )
    conversaciones_usernames.discard(usuario.username)
    conversaciones = [red.obtener_usuario(u) for u in conversaciones_usernames if red.obtener_usuario(u)]

    return render_template(
        'feed.html',
        publicaciones=publicaciones,
        conversaciones=conversaciones
    )

def calcular_edad(fecha_nacimiento):
    hoy = datetime.date.today()
    nacimiento = datetime.datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))

# Ruta para ver tu propio perfil
@app.route('/perfil')
def perfil():
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])

    # Para el perfil propio
    amigos_usernames = list(red.grafo.neighbors(usuario.username))
    amigos = [red.obtener_usuario(u) for u in amigos_usernames]

    fecha_nacimiento = usuario.datos_personales.get('fecha_nacimiento')
    edad = calcular_edad(fecha_nacimiento) if fecha_nacimiento else 0
    recomendados = []
    return render_template('profile.html', usuario=usuario, edad=edad, recomendados=recomendados, amigos=amigos)

# Ruta para ver el perfil de otro usuario
@app.route('/ver_perfil/<username>')
def ver_perfil(username):
    usuario = red.obtener_usuario(username)
    if not usuario:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for('usuarios'))
    externo = (username != session['username'])
    amigos_usernames = list(red.grafo.neighbors(username))
    amigos = [red.obtener_usuario(u) for u in amigos_usernames]
    es_amigo = session['username'] in amigos_usernames

    amigos_en_comun = []
    if externo:
        mis_amigos = set(red.grafo.neighbors(session['username']))
        sus_amigos = set(amigos_usernames)
        amigos_en_comun = [red.obtener_usuario(u) for u in mis_amigos & sus_amigos if u != session['username']]

    recomendados = []
    if not externo:
        recomendaciones_usernames = red.recomendar_amigos(session['username'])
        recomendados = [red.obtener_usuario(u) for u in recomendaciones_usernames]

    # --- Cálculo de edad ---
    fecha_nacimiento = usuario.datos_personales.get('fecha_nacimiento')
    edad = calcular_edad(fecha_nacimiento) if fecha_nacimiento else 0

    return render_template(
        'profile.html',
        usuario=usuario,
        externo=externo,
        es_amigo=es_amigo,
        recomendados=recomendados,
        amigos=amigos,
        amigos_en_comun=amigos_en_comun,
        edad=edad
    )

@app.route('/editar_perfil', methods=['GET', 'POST'])
def editar_perfil():
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    categorias = ["musica", "libros", "videojuegos", "deportes", "peliculas", "arte",
                  "ciencia", "historia", "tecnologia", "moda", "viajes", "comida", "animales", "naturaleza", "otros"]
    if request.method == 'POST':
        usuario.datos_personales['nombre'] = request.form['nombre']
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        usuario.datos_personales['fecha_nacimiento'] = fecha_nacimiento
        if fecha_nacimiento:
            hoy = datetime.date.today()
            nacimiento = datetime.datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
            edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
            usuario.datos_personales['edad'] = edad

        # AGREGA ESTO:
        usuario.datos_personales['ciudad'] = request.form.get('ciudad', '')
        usuario.datos_personales['descripcion'] = request.form.get('descripcion', '')

        intereses = {}
        for cat in categorias:
            if cat in request.form:
                intereses[cat] = request.form.get(f"detalle_{cat}", "")
        usuario.intereses = intereses
        usuario.privacidad = {
            "nombre": request.form.get("privacidad_nombre") == 'on',
            "edad": request.form.get("privacidad_edad") == 'on'
        }
        # --- Guardar avatar si se sube uno nuevo ---
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                AVATAR_FOLDER = os.path.join(app.root_path, 'static', 'avatars')
                os.makedirs(AVATAR_FOLDER, exist_ok=True)
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = secure_filename(f"{session['username']}_avatar.{ext}")
                filepath = os.path.join(AVATAR_FOLDER, filename)
                print("Guardando avatar en:", filepath)  # Para depuración
                file.save(filepath)
                usuario.avatar = filename
            else:
                print("Archivo no permitido o sin nombre")
        red.guardar_datos()
        flash("Perfil actualizado correctamente.", "success")
        return redirect(url_for('perfil'))
    return render_template('edit_profile.html', usuario=usuario, categorias=categorias)

@app.route('/usuarios', methods=['GET', 'POST'])
def usuarios():
    if 'username' not in session:
        return redirect(url_for('login'))
    busqueda = request.args.get('busqueda', '').lower()
    filtro = request.args.get('filtro', '')
    todos = [red.obtener_usuario(u) for u in red.listar_usuarios() if u != session['username']]
    amigos = list(red.grafo.neighbors(session['username']))
    if busqueda:
        todos = [u for u in todos if busqueda in u.username.lower()]
    if filtro == 'amigos':
        todos = [u for u in todos if u.username in amigos]
    elif filtro == 'noamigos':
        todos = [u for u in todos if u.username not in amigos]
    # Aquí convertimos los recomendados a objetos Usuario
    recomendaciones_usernames = red.recomendar_amigos(session['username'])
    recomendaciones = [red.obtener_usuario(u) for u in recomendaciones_usernames]
    return render_template('usuarios.html', usuarios=todos, recomendaciones=recomendaciones, amigos=amigos)

@app.route('/buscar', methods=['GET', 'POST'])
def buscar():
    if 'username' not in session:
        return redirect(url_for('login'))
    resultados = None
    if request.method == 'POST':
        query = request.form['query'].lower()
        resultados = [u for u in red.listar_usuarios() if query in u.lower() and u != session['username']]
    return render_template('buscar.html', resultados=resultados)

@app.route('/enviar_solicitud/<username>')
def enviar_solicitud(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    destino = red.obtener_usuario(username)
    if username not in usuario.solicitudes_enviadas and username != usuario.username:
        usuario.solicitudes_enviadas.append(username)
        destino.solicitudes_recibidas.append(usuario.username)
        red.guardar_datos()
        flash("Solicitud enviada.", "success")
    return redirect(url_for('usuarios'))

@app.route('/solicitudes')
def solicitudes():
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    solicitudes_obj = [red.obtener_usuario(u) for u in usuario.solicitudes_recibidas]
    return render_template('solicitudes.html', solicitudes=solicitudes_obj)

@app.route('/aceptar_solicitud/<username>')
def aceptar_solicitud(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    if username in usuario.solicitudes_recibidas:
        usuario.solicitudes_recibidas.remove(username)
        otro = red.obtener_usuario(username)
        if usuario.username in otro.solicitudes_enviadas:
            otro.solicitudes_enviadas.remove(usuario.username)
        red.conectar_usuarios(usuario.username, username)
        red.guardar_datos()
        flash("Ahora son amigos.", "success")
    return redirect(url_for('solicitudes'))

@app.route('/rechazar_solicitud/<username>')
def rechazar_solicitud(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    if username in usuario.solicitudes_recibidas:
        usuario.solicitudes_recibidas.remove(username)
        otro = red.obtener_usuario(username)
        otro.solicitudes_enviadas = [u for u in otro.solicitudes_enviadas if u != usuario.username]
        red.guardar_datos()
        flash("Solicitud rechazada.", "info")
    return redirect(url_for('solicitudes'))

@app.route('/amigos')
def amigos():
    usuario = red.obtener_usuario(session['username'])
    lista_amigos = [red.obtener_usuario(u) for u in red.grafo.neighbors(usuario.username)]
    return render_template('amigos.html', amigos=lista_amigos)

@app.route('/eliminar_amigo/<username>')
def eliminar_amigo(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    if red.grafo.has_edge(session['username'], username):
        red.grafo.remove_edge(session['username'], username)
        red.guardar_datos()
        flash("Amigo eliminado.", "info")
    return redirect(url_for('amigos'))

@app.route('/subir_foto', methods=['GET', 'POST'])
def subir_foto():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files['foto']
        descripcion = request.form.get('descripcion', '')
        if file and allowed_file(file.filename):
            FOTOS_FOLDER = os.path.join(app.root_path, 'static', 'fotos')
            os.makedirs(FOTOS_FOLDER, exist_ok=True)
            filename = secure_filename(f"{session['username']}_{file.filename}")
            filepath = os.path.join(FOTOS_FOLDER, filename)
            file.save(filepath)
            usuario = red.obtener_usuario(session['username'])
            foto = Foto(filename, descripcion, session['username'])
            usuario.fotos.append(foto)
            red.guardar_datos()
            flash("Foto subida correctamente.", "success")
            return redirect(url_for('feed'))
        else:
            flash("Archivo no permitido.", "danger")
    return render_template('subir_foto.html')

@app.route('/comentar_foto/<autor>/<filename>', methods=['POST'])
def comentar_foto(autor, filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    texto = request.form['comentario']
    usuario = red.obtener_usuario(autor)
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if foto:
        # Busca el máximo id actual
        nuevo_id = max([c["id"] for c in foto.comentarios], default=0) + 1
        foto.comentarios.append({
            "id": nuevo_id,
            "usuario": session['username'],  # <-- debe ser el username
            "texto": texto
        })
        red.guardar_datos()
    return redirect(url_for('feed'))

@app.route('/like_foto/<autor>/<filename>')
def like_foto(autor, filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(autor)
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if foto:
        if session['username'] in foto.likes:
            foto.likes.remove(session['username'])  # Quitar like
        else:
            foto.likes.add(session['username'])     # Dar like
        red.guardar_datos()
    return redirect(request.referrer or url_for('feed'))

@app.route('/eliminar_foto/<filename>', methods=['POST'])
def eliminar_foto(filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if foto:
        usuario.fotos.remove(foto)
        ruta_foto = os.path.join(app.root_path, 'static', 'fotos', filename)
        if os.path.exists(ruta_foto):
            os.remove(ruta_foto)
        red.guardar_datos()
        flash("Foto eliminada correctamente.", "success")
    else:
        flash("No se encontró la foto.", "danger")
    # Cambia esto:
    # return redirect(url_for('perfil'))
    # Por esto:
    return redirect(url_for('ver_perfil', username=usuario.username))

@app.route('/foto/<username>/<filename>', methods=['GET', 'POST'])
def ver_foto(username, filename):
    usuario = red.obtener_usuario(username)
    if not usuario:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for('feed'))
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if not foto:
        flash("Foto no encontrada.", "danger")
        return redirect(url_for('ver_perfil', username=username))
    if request.method == 'POST':
        comentario = request.form.get('comentario')
        if comentario and 'username' in session:
            nuevo_id = max([c["id"] for c in foto.comentarios if isinstance(c, dict)], default=0) + 1
            foto.comentarios.append({
                "id": nuevo_id,
                "usuario": session['username'],  # <-- debe ser el username
                "texto": comentario
            })
            red.guardar_datos()
    return render_template('ver_foto.html', usuario=usuario, foto=foto)

@app.route('/editar_comentario/<autor>/<filename>/<int:comentario_id>', methods=['POST'])
def editar_comentario(autor, filename, comentario_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(autor)
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if foto:
        for comentario in foto.comentarios:
            if comentario['id'] == comentario_id and comentario['usuario'] == session['username']:
                comentario['texto'] = request.form['nuevo_comentario']
                red.guardar_datos()
                break
    return redirect(request.referrer or url_for('feed'))

@app.route('/eliminar_comentario/<autor>/<filename>/<int:comentario_id>', methods=['POST'])
def eliminar_comentario(autor, filename, comentario_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(autor)
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if foto:
        foto.comentarios = [c for c in foto.comentarios if not (c['id'] == comentario_id and c['usuario'] == session['username'])]
        red.guardar_datos()
    return redirect(request.referrer or url_for('feed'))

@app.route('/mensajes/<username>', methods=['GET', 'POST'])
def mensajes(username):
    usuario = red.obtener_usuario(session['username'])
    otro = red.obtener_usuario(username)
    if request.method == 'POST':
        texto = request.form['mensaje']
        nuevo_mensaje = {
            'emisor': usuario.username,
            'receptor': otro.username,
            'texto': texto,
            'fecha': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        if not hasattr(usuario, 'mensajes_enviados'):
            usuario.mensajes_enviados = []
        usuario.mensajes_enviados.append(nuevo_mensaje)
        if not hasattr(otro, 'mensajes_recibidos'):
            otro.mensajes_recibidos = []
        otro.mensajes_recibidos.append(nuevo_mensaje)
        red.guardar_datos()
        return redirect(url_for('mensajes', username=otro.username))
    conversacion = obtener_conversacion(usuario.username, otro.username)
    return render_template('mensajes.html', usuario=usuario, otro=otro, mensajes=conversacion)

@app.route('/enviar_mensaje/<username>', methods=['GET', 'POST'])
def enviar_mensaje(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    emisor = session['username']
    receptor = username
    usuario_emisor = red.obtener_usuario(emisor)
    usuario_receptor = red.obtener_usuario(receptor)
    if request.method == 'POST':
        texto = request.form['mensaje']
        mensaje = Mensaje(emisor, receptor, texto)
        usuario_emisor.mensajes_enviados.append(mensaje)
        usuario_receptor.mensajes_recibidos.append(mensaje)
        red.guardar_datos()
        flash("Mensaje enviado.", "success")
        return redirect(url_for('enviar_mensaje', username=username))
    # Mostrar la conversación (simple: todos los mensajes entre ambos)
    conversacion = []
    for m in usuario_emisor.mensajes_enviados:
        if m.receptor == receptor:
            conversacion.append(m)
    for m in usuario_emisor.mensajes_recibidos:
        if m.emisor == receptor:
            conversacion.append(m)
    conversacion.sort(key=lambda x: x.fecha)
    return render_template('mensajes.html', otro=usuario_receptor, conversacion=conversacion)

@app.route('/confirmar/<token>')
def confirmar_correo(token):
    email = verificar_token(token)
    if not email:
        flash("El enlace de confirmación es inválido o ha expirado.", "danger")
        return redirect(url_for('login'))
    usuario = red.obtener_usuario_por_email(email)
    if usuario:
        usuario.verificado = True
        red.guardar_datos()
        flash("¡Correo confirmado! Ahora puedes iniciar sesión.", "success")
    return redirect(url_for('login'))

@app.route('/recuperar_contrasena', methods=['GET', 'POST'])
def recuperar_contrasena():
    if request.method == 'POST':
        email = request.form['email']
        usuario = red.obtener_usuario_por_email(email)
        if usuario:
            token = generar_token(email)
            enlace = url_for('resetear_contrasena', token=token, _external=True)
            msg = Message('Recupera tu contraseña', sender='tu-correo', recipients=[email])
            msg.body = f'Para restablecer tu contraseña, haz clic aquí: {enlace}'
            mail.send(msg)
        flash("Si el correo existe, se ha enviado un enlace de recuperación.", "info")
        return redirect(url_for('login'))
    return render_template('recuperar_contrasena.html', ocultar_nav=True)

@app.route('/resetear_contrasena/<token>', methods=['GET', 'POST'])
def resetear_contrasena(token):
    email = verificar_token(token)
    if not email:
        flash("El enlace es inválido o ha expirado.", "danger")
        return redirect(url_for('login'))
    if request.method == 'POST':
        nueva = request.form['nueva_contrasena']
        usuario = red.obtener_usuario_por_email(email)
        if usuario:
            usuario.password_hash = usuario.hashear_contrasena(nueva)
            red.guardar_datos()
            flash("Contraseña restablecida. Ahora puedes iniciar sesión.", "success")
            return redirect(url_for('login'))
    return render_template('resetear_contrasena.html', ocultar_nav=True)

@app.route('/reenviar_confirmacion', methods=['POST'])
def reenviar_confirmacion():
    username = request.form.get('username')
    usuario = red.obtener_usuario(username)
    if usuario and not getattr(usuario, "verificado", False):
        token = generar_token(usuario.datos_personales['email'])
        enlace = url_for('confirmar_correo', token=token, _external=True)
        msg = Message('Confirma tu correo', sender='tu-correo', recipients=[usuario.datos_personales['email']])
        msg.body = f'Por favor confirma tu correo haciendo clic en este enlace: {enlace}'
        mail.send(msg)
        flash("Se ha reenviado el correo de confirmación.", "info")
    else:
        flash("No se pudo reenviar el correo de confirmación.", "danger")
    return render_template('login.html', ocultar_nav=True, username=username)

@app.route('/editar_descripcion/<filename>', methods=['POST'])
def editar_descripcion(filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    nueva_desc = request.form['nueva_descripcion']
    for foto in getattr(usuario, 'fotos', []):
        if foto.filename == filename:
            foto.descripcion = nueva_desc
            red.guardar_datos()
            break
    return redirect(url_for('perfil'))

@app.route('/eliminar_publicacion/<filename>', methods=['POST'])
def eliminar_publicacion(filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    fotos = getattr(usuario, 'fotos', [])
    nueva_lista = [foto for foto in fotos if foto.filename != filename]
    if len(nueva_lista) < len(fotos):
        usuario.fotos = nueva_lista
        red.guardar_datos()
    return redirect(url_for('perfil'))

def generar_token(email):
    s = URLSafeTimedSerializer(app.secret_key)
    return s.dumps(email, salt="email-confirm")

def verificar_token(token, max_age=3600):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        email = s.loads(token, salt="email-confirm", max_age=max_age)
    except Exception:
        return None
    return email

def obtener_conversacion(username1, username2):
    """Devuelve la lista de mensajes entre dos usuarios, ordenada por fecha."""
    usuario1 = red.obtener_usuario(username1)
    usuario2 = red.obtener_usuario(username2)
    mensajes = []
    # Mensajes enviados de usuario1 a usuario2
    for m in getattr(usuario1, 'mensajes_enviados', []):
        if getattr(m, 'receptor', None) == username2 or (isinstance(m, dict) and m.get('receptor') == username2):
            mensajes.append({
                'emisor': username1,
                'texto': m.texto if hasattr(m, 'texto') else m.get('texto'),
                'fecha': m.fecha if hasattr(m, 'fecha') else m.get('fecha')
            })
    # Mensajes enviados de usuario2 a usuario1
    for m in getattr(usuario2, 'mensajes_enviados', []):
        if getattr(m, 'receptor', None) == username1 or (isinstance(m, dict) and m.get('receptor') == username1):
            mensajes.append({
                'emisor': username2,
                'texto': m.texto if hasattr(m, 'texto') else m.get('texto'),
                'fecha': m.fecha if hasattr(m, 'fecha') else m.get('fecha')
            })
    # Ordena por fecha si existe
    mensajes.sort(key=lambda x: x['fecha'])
    return mensajes

def guardar_conversacion(username1, username2, conversacion):
    """No hace nada porque los mensajes ya se guardan en los usuarios."""
    pass

# Convierte comentarios antiguos (tuplas) a diccionarios
for username in red.listar_usuarios():
    usuario = red.obtener_usuario(username)
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
red.guardar_datos()
print("Comentarios convertidos a diccionarios.")

@app.route('/publicacion/<username>/<filename>', methods=['GET', 'POST'])
def ver_publicacion(username, filename):
    usuario = red.obtener_usuario(username)
    foto = next((f for f in usuario.fotos if f.filename == filename), None)
    if not foto:
        flash("Publicación no encontrada.", "danger")
        return redirect(url_for('ver_perfil', username=username))

    if not hasattr(foto, 'likes') or foto.likes is None:
        foto.likes = set()
    # Convierte a lista para Jinja2
    foto.likes = list(foto.likes)
    if not hasattr(foto, 'comentarios') or foto.comentarios is None:
        foto.comentarios = []

    if request.method == 'POST':
        if 'like' in request.form and 'username' in session:
            user = session['username']
            if user in foto.likes:
                foto.likes.remove(user)  # Quitar el like si ya lo tiene
            else:
                foto.likes.add(user)     # Agregar el like si no lo tiene
            red.guardar_datos()
            # Redirige después de dar like
            return redirect(url_for('ver_publicacion', username=username, filename=filename))
        elif 'comentario' in request.form and 'username' in session:
            comentario = request.form['comentario']
            foto.comentarios.append({'usuario': session['username'], 'texto': comentario})  # <-- Cambia 'autor' por 'usuario'
            red.guardar_datos()
            # Redirige después de comentar
            return redirect(url_for('ver_publicacion', username=username, filename=filename))

    return render_template('publicacion.html', usuario=usuario, foto=foto)

if __name__ == "__main__":
    print("Servidor corriendo en: http://localhost:5000/")
    app.run(debug=True)
