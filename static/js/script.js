// IIFE så vi inte skräpar ner global scope i onödan,
// men exponerar det vi behöver via window.
(function () {
  // ─────────────────────────────────────────────
  // 1) Filnamnet under "Ingen fil vald"
  // ─────────────────────────────────────────────
  window.showFilename = function (input) {
    var label = document.getElementById("filename");
    if (!label) return;

    if (!input.files || input.files.length === 0) {
      label.textContent = "Ingen fil vald";
      return;
    }

    var file = input.files[0];
    label.textContent = file.name;
  };

  // ─────────────────────────────────────────────
  // 3) (Liten bonus) Drag & drop highlight
  // ─────────────────────────────────────────────
  var dropZone = document.querySelector(".adminui-drop-zone");
  var fileInput = document.getElementById("excel");

  if (dropZone && fileInput) {
    // Dra över = highlight
    ["dragenter", "dragover"].forEach(function (eventName) {
      dropZone.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add("is-dragover");
      });
    });

    ["dragleave", "drop"].forEach(function (eventName) {
      dropZone.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove("is-dragover");
      });
    });

    dropZone.addEventListener("drop", function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files.length) return;
      fileInput.files = e.dataTransfer.files;
      window.showFilename(fileInput);
    });
  }
})();
