"""Auto-recuperación del frontend cuando Streamlit Cloud redeploya la app.

EL PROBLEMA
-----------
Streamlit sirve su interfaz como una SPA con los archivos JS versionados por hash
(`static/js/index.<hash>.js`) y los carga con IMPORT DINÁMICO, a pedido. Cada vez
que la app se redeploya, esos hashes cambian y los archivos viejos dejan de
existir en el servidor.

Una pestaña que quedó abierta desde antes del deploy sigue teniendo en su caché
el `index.html` viejo, así que pide un chunk que ya no está y el navegador tira:

    TypeError: Failed to fetch dynamically imported module:
    https://…/static/js/index.<hash viejo>.js

Streamlit muestra ese error EN EL LUGAR del elemento que necesitaba el chunk —
por ejemplo el `components.html` de la cookie de sesión en el login — así que
parece que se rompió el login cuando en realidad lo único que pasa es que ese
navegador tiene el frontend viejo. A una persona le anda perfecto y a otra no,
según cuándo abrió la pestaña y qué tiene cacheado. Es un problema conocido de
todas las SPA con chunks hasheados, no algo de esta app.

LA SOLUCIÓN
-----------
Se instala un vigía en la ventana principal: si aparece ese error (como error
suelto o como promesa rechazada), la página se recarga sola una vez para bajar
el `index.html` nuevo. Con un tope de intentos guardado en sessionStorage para
no entrar nunca en un bucle de recargas, y un cartel con instrucciones si aun
así no se recupera.

El script vive en un `components.html` de altura 0 (el mismo mecanismo que ya
usa auth_persist para las cookies) y trabaja sobre `parent`, que es la ventana
real de la app.
"""
import streamlit as st
import streamlit.components.v1 as components

_MAX_INTENTOS = 2
_CLAVE = "worms_reload_chunk"

_JS = """
<script>
(function () {
  var W;
  try { W = window.parent || window; } catch (e) { W = window; }
  if (!W || W.__wormsChunkGuard) return;
  W.__wormsChunkGuard = 1;

  var CLAVE = "%(clave)s", MAX = %(max)d;

  function esErrorDeChunk(msg) {
    msg = String(msg || "");
    return /Failed to fetch dynamically imported module/i.test(msg)
        || /error loading dynamically imported module/i.test(msg)
        || /Importing a module script failed/i.test(msg)
        || /ChunkLoadError/i.test(msg)
        || /Loading chunk [\\w-]+ failed/i.test(msg);
  }

  function intentos(n) {
    try {
      if (n === undefined) return parseInt(W.sessionStorage.getItem(CLAVE) || "0", 10) || 0;
      if (n === null) W.sessionStorage.removeItem(CLAVE);
      else W.sessionStorage.setItem(CLAVE, String(n));
    } catch (e) { return 0; }
    return n || 0;
  }

  function cartel() {
    try {
      if (W.document.getElementById("worms-chunk-aviso")) return;
      var d = W.document.createElement("div");
      d.id = "worms-chunk-aviso";
      d.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:99999;padding:14px 18px;" +
        "background:#fef3c7;color:#7c2d12;font:600 14px/1.45 system-ui,sans-serif;" +
        "border-bottom:2px solid #d97706;box-shadow:0 2px 10px rgba(0,0,0,.12)";
      d.innerHTML = "<b>La p\\u00e1gina qued\\u00f3 con una versi\\u00f3n vieja guardada en este " +
        "navegador.</b><br>Cerr\\u00e1 esta pesta\\u00f1a y volv\\u00e9 a entrar, o " +
        "recarg\\u00e1 la p\\u00e1gina forzando la actualizaci\\u00f3n con " +
        "<kbd style='background:#fff;border:1px solid #d6d3d1;border-bottom-width:2px;" +
        "border-radius:4px;padding:1px 5px'>Ctrl</kbd> + " +
        "<kbd style='background:#fff;border:1px solid #d6d3d1;border-bottom-width:2px;" +
        "border-radius:4px;padding:1px 5px'>May\\u00fas</kbd> + " +
        "<kbd style='background:#fff;border:1px solid #d6d3d1;border-bottom-width:2px;" +
        "border-radius:4px;padding:1px 5px'>R</kbd>. " +
        "No se pierde nada: la carga que estabas armando queda guardada como borrador.";
      W.document.body.appendChild(d);
    } catch (e) {}
  }

  var recargando = false;
  function recuperar() {
    if (recargando) return;
    var n = intentos();
    if (n >= MAX) { cartel(); return; }   // ya se intent\\u00f3: no entrar en bucle
    recargando = true;
    intentos(n + 1);
    try {
      // el service worker / la cach\\u00e9 del sitio son justamente lo que guarda el
      // index.html viejo: se limpian antes de recargar
      if (W.caches && W.caches.keys) {
        W.caches.keys().then(function (ks) { ks.forEach(function (k) { W.caches.delete(k); }); });
      }
    } catch (e) {}
    setTimeout(function () { try { W.location.reload(); } catch (e) {} }, 350);
  }

  W.addEventListener("error", function (ev) {
    if (esErrorDeChunk(ev && (ev.message || (ev.error && ev.error.message)))) recuperar();
  }, true);
  W.addEventListener("unhandledrejection", function (ev) {
    var r = ev && ev.reason;
    if (esErrorDeChunk(r && (r.message || r))) recuperar();
  });

  // si la app carg\\u00f3 bien y sigue viva un rato, el contador se limpia solo:
  // as\\u00ed el pr\\u00f3ximo deploy vuelve a tener sus dos intentos.
  try { W.setTimeout(function () { intentos(null); }, 20000); } catch (e) {}
})();
</script>
""" % {"clave": _CLAVE, "max": _MAX_INTENTOS}


def instalar():
    """Se llama UNA vez por sesión, lo antes posible en app.py."""
    ss = st.session_state
    if ss.get("_worms_autorecarga"):
        return
    ss["_worms_autorecarga"] = True
    try:
        components.html(_JS, height=0)
    except Exception:
        pass
