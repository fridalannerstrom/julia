(function () {
  // ─────────────────────────────────────────────
  // 1) Filnamn för Excel
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
  // 2) Extra PDF-filer (max 5)
  // ─────────────────────────────────────────────
  window.updateExtraFiles = function (input) {
    var list = document.getElementById("extra-files-list");
    if (!list) return;

    list.innerHTML = "";

    if (!input.files || input.files.length === 0) {
      list.textContent = "Inga filer valda";
      return;
    }

    var files = Array.from(input.files);
    var maxFiles = 5;

    if (files.length > maxFiles) {
      // Vi visar en liten varning, backend kommer ändå bara använda de första 5
      alert("Max 5 filer. Endast de första 5 kommer att användas.");
      files = files.slice(0, maxFiles);
    }

    files.forEach(function (file) {
      var item = document.createElement("div");
      item.className = "adminui-filelist-item";
      item.textContent = file.name;
      list.appendChild(item);
    });
  };

  // ─────────────────────────────────────────────
  // 4) Drag & drop – Excel
  // ─────────────────────────────────────────────
  var dropZone = document.querySelector(".adminui-drop-zone"); // din första (Excel)
  var fileInput = document.getElementById("excel");

  if (dropZone && fileInput) {
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

  // ─────────────────────────────────────────────
  // 5) Drag & drop – extra PDF-filer
  // ─────────────────────────────────────────────
  var dropZoneExtra = document.querySelector(".adminui-drop-zone-extra");
  var extraInput = document.getElementById("extra_files");

  if (dropZoneExtra && extraInput) {
    ["dragenter", "dragover"].forEach(function (eventName) {
      dropZoneExtra.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZoneExtra.classList.add("is-dragover");
      });
    });

    ["dragleave", "drop"].forEach(function (eventName) {
      dropZoneExtra.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropZoneExtra.classList.remove("is-dragover");
      });
    });

    dropZoneExtra.addEventListener("drop", function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files.length) return;
      extraInput.files = e.dataTransfer.files;
      window.updateExtraFiles(extraInput);
    });

    // Klick på zonen -> öppna filväljare
    dropZoneExtra.addEventListener("click", function () {
      extraInput.click();
    });
  }
})();