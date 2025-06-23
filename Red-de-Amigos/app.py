from flask import Flask, render_template, request, redirect, session, url_for, flash
from redsocial import RedSocial, Usuario
from werkzeug.utils import secure_filename
import os

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__)
app.secret_key = 'clave_secreta_segura'
red = RedSocial()

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
        username = request.form['username']
        password = request.form['password']
        nombre = request.form['nombre']
        edad = request.form['edad']
        intereses = {}
        categorias = ["musica", "libros", "videojuegos", "deportes", "peliculas", "arte",
                      "ciencia", "historia", "tecnologia", "moda", "viajes", "comida", "animales", "naturaleza", "otros"]
        for cat in categorias:
            if cat in request.form:
                intereses[cat] = request.form.get(f"detalle_{cat}", "")
        privacidad = {
            "nombre": request.form.get("privacidad_nombre") == 'on',
            "edad": request.form.get("privacidad_edad") == 'on'
        }
        usuario = Usuario(username, password, {"nombre": nombre, "edad": edad}, intereses, privacidad)
        try:
            red.registrar_usuario(usuario)
            flash("Registro exitoso. Ahora puedes iniciar sesión.", "success")
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
            session['username'] = username
            return redirect(url_for('feed'))
        flash("Usuario o contraseña incorrectos.", "danger")
        return render_template('login.html')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/feed')
def feed():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('feed.html')

@app.route('/perfil')
def perfil():
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    recomendados = red.recomendar_amigos(session['username'])
    return render_template('profile.html', usuario=usuario, recomendados=recomendados)

@app.route('/ver_perfil/<username>')
def ver_perfil(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    if username not in red.listar_usuarios():
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for('feed'))
    usuario = red.obtener_usuario(username)
    es_amigo = red.grafo.has_edge(session['username'], username)
    externo = (username != session['username'])
    return render_template('profile.html', usuario=usuario, recomendados=[], es_amigo=es_amigo, externo=externo)

@app.route('/editar_perfil', methods=['GET', 'POST'])
def editar_perfil():
    if 'username' not in session:
        return redirect(url_for('login'))
    usuario = red.obtener_usuario(session['username'])
    categorias = ["musica", "libros", "videojuegos", "deportes", "peliculas", "arte",
                  "ciencia", "historia", "tecnologia", "moda", "viajes", "comida", "animales", "naturaleza", "otros"]
    if request.method == 'POST':
        usuario.datos_personales['nombre'] = request.form['nombre']
        usuario.datos_personales['edad'] = request.form['edad']
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
    amigos = list(red.grafo.neighbors(session['username']))
    resultados = []
    if request.method == 'POST':
        query = request.form['query'].lower()
        resultados = [u for u in red.listar_usuarios() if query in u.lower() and u != session['username']]
    else:
        resultados = [u for u in red.listar_usuarios() if u != session['username']]
    return render_template('usuarios.html', resultados=resultados, amigos=amigos)

@app.route('/buscar', methods=['GET', 'POST'])
def buscar():
    if 'username' not in session:
        return redirect(url_for('login'))
    resultados = []
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
    return render_template('solicitudes.html', solicitudes=usuario.solicitudes_recibidas)

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
    if 'username' not in session:
        return redirect(url_for('login'))
    amigos = list(red.grafo.neighbors(session['username']))
    return render_template('amigos.html', amigos=amigos)

@app.route('/eliminar_amigo/<username>')
def eliminar_amigo(username):
    if 'username' not in session:
        return redirect(url_for('login'))
    if red.grafo.has_edge(session['username'], username):
        red.grafo.remove_edge(session['username'], username)
        red.guardar_datos()
        flash("Amigo eliminado.", "info")
    return redirect(url_for('amigos'))

if __name__ == '__main__':
    app.run(debug=True)