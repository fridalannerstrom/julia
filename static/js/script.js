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
        list.textContent = "Inget CV uppladdat";
        return;
    }

    var file = input.files[0];  // bara första filen används
    var item = document.createElement("div");
    item.className = "adminui-filelist-item";
    item.textContent = file.name;
    list.appendChild(item);
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
var extraInput = document.getElementById("cv_file");

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
    // ta bara första filen som CV
    var dtFiles = e.dataTransfer.files;
    if (dtFiles.length > 0) {
      var dataTransfer = new DataTransfer();
      dataTransfer.items.add(dtFiles[0]);
      extraInput.files = dataTransfer.files;
    }
    window.updateExtraFiles(extraInput);
  });

  // Klick på zonen -> öppna filväljare
  dropZoneExtra.addEventListener("click", function () {
    extraInput.click();
  });
}
})();