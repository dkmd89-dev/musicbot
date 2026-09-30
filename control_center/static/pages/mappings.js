// control_center/static/pages/mappings.js
// Mapping-Administration (Phase 5). Seitengerüst: prüft die Anmeldung über
// die gemeinsamen Helfer aus common.js. Die Mapping-Karten und Editoren
// folgen in den nächsten Ausbaustufen; Fachlogik liegt ausschließlich im
// Backend (services/mapping_admin.py), diese Seite zeigt nur an.
(function () {
  "use strict";

  function initPage() {
    checkAuth().then((who) => {
      if (!who) return;
    });
  }

  initPage();
})();
