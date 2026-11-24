/* LBA Print Server — utilidades del panel (sin dependencias externas). */
(function () {
  "use strict";
  // Confirmación de formularios peligrosos (.confirmable[data-msg])
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (form && form.classList && form.classList.contains("confirmable")) {
      var msg = form.getAttribute("data-msg") || "¿Seguro?";
      if (!window.confirm(msg)) {
        ev.preventDefault();
      }
    }
  }, true);
  // Ocultar flashes tras 6s (no errores)
  setTimeout(function () {
    document.querySelectorAll(".flash-ok").forEach(function (el) {
      el.style.transition = "opacity .6s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 700);
    });
  }, 6000);
})();
