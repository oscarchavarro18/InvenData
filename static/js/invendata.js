/* InvenData · comportamiento de la interfaz.
 *
 * Solo mejora lo que ya funciona sin JavaScript: menús, hojas, buscador rápido, avisos,
 * cifras animadas y apariciones suaves. Nada de esto guarda datos ni cambia permisos.
 */
(function () {
  "use strict";

  var movimientoReducido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var app = document.getElementById("app");
  var abiertos = []; // capas abiertas, la última arriba: se cierran con Escape en orden

  function cerrarUltima() {
    var capa = abiertos.pop();
    if (capa) { capa.cerrar(); }
  }

  function bloquearScroll(si) {
    document.body.classList.toggle("menu-abierto", si);
  }

  /* ---------- Menú: grupos desplegables en escritorio, hoja en el celular ---------- */

  var botonesMenu = document.querySelectorAll("[data-abrir-menu]");
  function abrirMenu(si) {
    if (!app) { return; }
    app.classList.toggle("menu-abierto", si);
    bloquearScroll(si);
    botonesMenu.forEach(function (b) { b.setAttribute("aria-expanded", si ? "true" : "false"); });
    if (si) {
      abiertos.push({ menu: true, cerrar: function () { abrirMenu(false); } });
    } else {
      abiertos = abiertos.filter(function (c) { return !c.menu; });
    }
  }
  botonesMenu.forEach(function (b) {
    b.addEventListener("click", function () { abrirMenu(true); });
  });
  document.querySelectorAll("[data-cerrar-menu]").forEach(function (el) {
    el.addEventListener("click", function () { abrirMenu(false); });
  });
  window.matchMedia("(min-width: 1024px)").addEventListener("change", function () {
    abrirMenu(false);
  });

  // Grupos del menú de escritorio: uno solo abierto a la vez. Se abren al pasar el mouse
  // (con un pequeño margen para cruzar hasta el panel) o con clic y teclado.
  var grupos = Array.prototype.slice.call(document.querySelectorAll(".menu__grupo"));
  var escritorio = window.matchMedia("(min-width: 1024px)");
  var conMouse = window.matchMedia("(hover: hover) and (pointer: fine)");
  var temporizador = null;

  function abrirGrupo(grupo) {
    clearTimeout(temporizador);
    grupos.forEach(function (g) {
      var abrir = g === grupo;
      g.classList.toggle("menu__grupo--abierto", abrir);
      var d = g.querySelector("[data-grupo]");
      if (d) { d.setAttribute("aria-expanded", abrir ? "true" : "false"); }
    });
  }
  function cerrarGrupos() { abrirGrupo(null); }

  grupos.forEach(function (grupo) {
    var disparador = grupo.querySelector("[data-grupo]");
    if (!disparador) { return; }
    disparador.addEventListener("click", function () {
      if (!escritorio.matches) { return; }
      var abierto = grupo.classList.contains("menu__grupo--abierto");
      abrirGrupo(abierto ? null : grupo);
    });
    grupo.addEventListener("mouseenter", function () {
      if (escritorio.matches && conMouse.matches) { abrirGrupo(grupo); }
    });
    grupo.addEventListener("mouseleave", function () {
      if (!escritorio.matches || !conMouse.matches) { return; }
      clearTimeout(temporizador);
      temporizador = setTimeout(function () {
        if (grupo.contains(document.activeElement)) { return; }
        grupo.classList.remove("menu__grupo--abierto");
        disparador.setAttribute("aria-expanded", "false");
      }, 160);
    });
    grupo.addEventListener("focusout", function (e) {
      if (!grupo.contains(e.relatedTarget)) {
        grupo.classList.remove("menu__grupo--abierto");
        disparador.setAttribute("aria-expanded", "false");
      }
    });
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".menu__grupo")) { cerrarGrupos(); }
  });

  /* ---------- Hojas (Registrar) ---------- */

  function abrirHoja(hoja) {
    hoja.hidden = false;
    bloquearScroll(true);
    var primero = hoja.querySelector("a, button:not(.hoja__velo)");
    if (primero) { primero.focus({ preventScroll: true }); }
    abiertos.push({
      cerrar: function () {
        hoja.hidden = true;
        bloquearScroll(false);
      }
    });
  }
  document.querySelectorAll("[data-abrir-hoja]").forEach(function (b) {
    b.addEventListener("click", function () {
      var hoja = document.getElementById(b.getAttribute("data-abrir-hoja"));
      if (hoja) { abrirHoja(hoja); }
    });
  });
  document.querySelectorAll("[data-cerrar-hoja]").forEach(function (b) {
    b.addEventListener("click", cerrarUltima);
  });

  /* ---------- Buscador rápido (Ctrl K) ---------- */

  var buscador = document.getElementById("buscador");
  var campo = document.querySelector("[data-buscador-campo]");
  var enlaces = Array.prototype.slice.call(document.querySelectorAll("[data-buscador-lista] a"));
  var vacio = document.querySelector("[data-buscador-vacio]");
  var marcado = 0;

  function normalizar(texto) {
    return texto.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }
  function visibles() {
    return enlaces.filter(function (a) { return !a.parentNode.hidden; });
  }
  function marcar(indice) {
    var lista = visibles();
    lista.forEach(function (a) { a.classList.remove("seleccionado"); });
    if (!lista.length) { return; }
    marcado = (indice + lista.length) % lista.length;
    lista[marcado].classList.add("seleccionado");
    lista[marcado].scrollIntoView({ block: "nearest" });
  }
  function filtrar() {
    var q = normalizar(campo.value.trim());
    var vistos = {};
    enlaces.forEach(function (a) {
      var clave = a.getAttribute("href") + a.textContent;
      var coincide = !q || normalizar(a.getAttribute("data-texto")).indexOf(q) !== -1;
      a.parentNode.hidden = !coincide || vistos[clave];
      vistos[clave] = true;
    });
    if (vacio) { vacio.hidden = visibles().length > 0; }
    marcar(0);
  }
  function abrirBuscador() {
    if (!buscador || !buscador.hidden) { return; }
    buscador.hidden = false;
    campo.value = "";
    filtrar();
    campo.focus();
    abiertos.push({ cerrar: function () { buscador.hidden = true; } });
  }
  if (buscador && campo) {
    document.querySelectorAll("[data-abrir-buscador]").forEach(function (b) {
      b.addEventListener("click", abrirBuscador);
    });
    document.querySelectorAll("[data-cerrar-buscador]").forEach(function (b) {
      b.addEventListener("click", cerrarUltima);
    });
    campo.addEventListener("input", filtrar);
    campo.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); marcar(marcado + 1); }
      if (e.key === "ArrowUp") { e.preventDefault(); marcar(marcado - 1); }
      if (e.key === "Enter") {
        var elegido = visibles()[marcado];
        if (elegido) { e.preventDefault(); window.location.href = elegido.href; }
      }
    });
  }

  document.addEventListener("keydown", function (e) {
    var tecla = e.key || "";
    var escribiendo = /input|textarea|select/i.test((e.target.tagName || "")) || e.target.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && tecla.toLowerCase() === "k") {
      e.preventDefault();
      abrirBuscador();
    } else if (tecla === "/" && !escribiendo) {
      e.preventDefault();
      abrirBuscador();
    } else if (tecla === "Escape") {
      if (abiertos.length) { cerrarUltima(); } else { cerrarGrupos(); }
    }
  });

  /* ---------- Confirmación de acciones delicadas (desactivar, activar…) ---------- */

  var dialogo = document.getElementById("confirmacion");
  if (dialogo) {
    var textoDialogo = dialogo.querySelector("[data-confirmacion-texto]");
    var aceptar = dialogo.querySelector("[data-aceptar-confirmacion]");
    var pendiente = null;
    var cerrarDialogo = function () {
      dialogo.hidden = true;
      bloquearScroll(false);
      pendiente = null;
    };
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form.hasAttribute || !form.hasAttribute("data-confirmar-accion")) { return; }
      if (form.dataset.confirmado === "si") { return; }
      e.preventDefault();
      pendiente = form;
      textoDialogo.textContent = form.getAttribute("data-confirmar-accion");
      var peligro = form.hasAttribute("data-peligro");
      aceptar.classList.toggle("boton--peligro-lleno", peligro);
      aceptar.textContent = peligro ? "Sí, desactivar" : "Confirmar";
      dialogo.hidden = false;
      bloquearScroll(true);
      aceptar.focus();
      abiertos.push({ cerrar: cerrarDialogo });
    });
    aceptar.addEventListener("click", function () {
      if (!pendiente) { return; }
      var form = pendiente;
      form.dataset.confirmado = "si";
      abiertos.pop();
      cerrarDialogo();
      if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
    });
    dialogo.querySelectorAll("[data-cerrar-confirmacion]").forEach(function (b) {
      b.addEventListener("click", function () { abiertos.pop(); cerrarDialogo(); });
    });
  }

  /* ---------- Menú de usuario ---------- */

  var menuUsuario = document.querySelector(".usuario-menu");
  if (menuUsuario) {
    document.addEventListener("click", function (e) {
      if (!menuUsuario.contains(e.target)) { menuUsuario.removeAttribute("open"); }
    });
  }

  /* ---------- Avisos ---------- */

  document.querySelectorAll(".alerta").forEach(function (aviso) {
    function quitar() {
      aviso.classList.add("alerta--saliendo");
      setTimeout(function () { aviso.remove(); }, 300);
    }
    var cerrar = aviso.querySelector(".alerta__cerrar");
    if (cerrar) { cerrar.addEventListener("click", quitar); }
    if (aviso.classList.contains("alerta-success")) { setTimeout(quitar, 6000); }
  });

  /* ---------- Barra superior con sombra al bajar ---------- */

  var barra = document.getElementById("barra-sup");
  if (barra) {
    var sombra = function () { barra.classList.toggle("con-sombra", window.scrollY > 4); };
    window.addEventListener("scroll", sombra, { passive: true });
    sombra();
  }

  /* ---------- Onda al tocar un botón ---------- */

  if (!movimientoReducido) {
    document.addEventListener("pointerdown", function (e) {
      var boton = e.target.closest(".boton");
      if (!boton || boton.disabled) { return; }
      var caja = boton.getBoundingClientRect();
      var onda = document.createElement("span");
      onda.className = "onda-boton";
      onda.style.left = e.clientX - caja.left + "px";
      onda.style.top = e.clientY - caja.top + "px";
      boton.appendChild(onda);
      setTimeout(function () { onda.remove(); }, 650);
    });
  }

  /* ---------- Cifras que cuentan hasta su valor ---------- */

  var formato = function (valor, decimales) {
    return valor.toLocaleString("es-CO", {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales
    });
  };
  function contar(el) {
    var fin = parseFloat(el.getAttribute("data-contar"));
    var decimales = parseInt(el.getAttribute("data-decimales") || "0", 10);
    if (isNaN(fin) || movimientoReducido) { return; }
    var nodo = el.firstChild && el.firstChild.nodeType === 3 ? el.firstChild : null;
    if (!nodo) { return; }
    var inicio = null;
    var duracion = 900;
    function paso(t) {
      if (inicio === null) { inicio = t; }
      var avance = Math.min((t - inicio) / duracion, 1);
      var suave = 1 - Math.pow(1 - avance, 3);
      nodo.nodeValue = formato(fin * suave, decimales) + " ";
      if (avance < 1) { requestAnimationFrame(paso); } else { nodo.nodeValue = formato(fin, decimales) + " "; }
    }
    requestAnimationFrame(paso);
  }

  /* ---------- Aparición suave al bajar ---------- */

  if ("IntersectionObserver" in window && !movimientoReducido) {
    var observador = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (entrada.isIntersecting) {
          entrada.target.classList.add("visible");
          if (entrada.target.hasAttribute("data-contar")) { contar(entrada.target); }
          observador.unobserve(entrada.target);
        }
      });
    }, { rootMargin: "0px 0px -40px 0px" });

    var alto = window.innerHeight;
    document.querySelectorAll(".contenido .tarjeta, .contenido .indicador, .rotulo, .cifra-bloque")
      .forEach(function (el) {
        if (el.getBoundingClientRect().top > alto) {
          el.classList.add("revelar");
          observador.observe(el);
        }
      });
    document.querySelectorAll("[data-contar]").forEach(function (el) { observador.observe(el); });
  }

  /* ---------- Inicio: la cadena del día filtra los pendientes ---------- */

  var etapas = document.querySelectorAll("[data-etapa]");
  if (etapas.length) {
    var filas = document.querySelectorAll("[data-de-etapa]");
    var quitarFiltro = document.querySelector("[data-quitar-filtro]");
    var sinPendientes = document.querySelector("[data-sin-pendientes]");
    var aplicar = function (etapa) {
      var hay = 0;
      etapas.forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-etapa") === etapa ? "true" : "false");
      });
      filas.forEach(function (fila) {
        var mostrar = !etapa || fila.getAttribute("data-de-etapa") === etapa;
        fila.hidden = !mostrar;
        if (mostrar) { hay += 1; }
      });
      if (quitarFiltro) { quitarFiltro.hidden = !etapa; }
      if (sinPendientes) { sinPendientes.hidden = hay > 0; }
    };
    etapas.forEach(function (b) {
      b.addEventListener("click", function () {
        var activa = b.getAttribute("aria-pressed") === "true";
        aplicar(activa ? null : b.getAttribute("data-etapa"));
      });
    });
    if (quitarFiltro) { quitarFiltro.addEventListener("click", function () { aplicar(null); }); }
  }

  /* ---------- Ingreso: ver la contraseña e indicar que está entrando ---------- */

  document.querySelectorAll("[data-ver-clave]").forEach(function (boton) {
    var entrada = document.getElementById(boton.getAttribute("data-ver-clave"));
    if (!entrada) { return; }
    boton.hidden = false;
    boton.addEventListener("click", function () {
      var ver = entrada.type === "password";
      entrada.type = ver ? "text" : "password";
      boton.textContent = ver ? "Ocultar" : "Mostrar";
      boton.setAttribute("aria-pressed", ver ? "true" : "false");
    });
  });
  document.querySelectorAll("form[data-enviando]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var boton = form.querySelector("[type=submit]");
      if (!boton) { return; }
      boton.setAttribute("aria-busy", "true");
      boton.innerHTML = '<svg class="icono girando" viewBox="0 0 24 24" aria-hidden="true">' +
        '<path d="M12 3a9 9 0 1 1-9 9"/></svg>' + form.getAttribute("data-enviando");
    });
  });
})();
