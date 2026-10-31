// Say back what was chosen in the browser's own file picker.
//
// The pickers are kennis's buttons over the browser's file inputs, which
// stay in the form and are what it sends. A form without a script shows
// the browser's own controls instead; this marks a picker it has taken
// over with `data-enhanced`, and the stylesheet hides the bare inputs
// only then.
//
// Nothing here composes a sentence: every word is the server's, in the
// picker's `data-said-*` attributes, with `{name}`, `{names}` and
// `{count}` the only parts filled in.
(function () {
  var SHOWN = 3;

  function filled(template, values) {
    return template.replace(/\{(\w+)\}/g, function (whole, key) {
      return key in values ? String(values[key]) : whole;
    });
  }

  function said(box, input) {
    var files = Array.prototype.slice.call(input.files);
    if (input.hasAttribute("webkitdirectory")) {
      var top = (files[0].webkitRelativePath || files[0].name).split("/")[0];
      return filled(box.dataset.saidFolder, { name: top, count: files.length });
    }
    if (files.length === 1) {
      return filled(box.dataset.saidOne, { name: files[0].name });
    }
    var names = files.slice(0, SHOWN).map(function (file) { return file.name; }).join(", ");
    if (files.length > SHOWN) {
      names = filled(box.dataset.saidMore, { names: names, count: files.length - SHOWN });
    }
    return filled(box.dataset.saidMany, { count: files.length, names: names });
  }

  function describe(box) {
    var parts = [];
    box.querySelectorAll('input[type="file"]').forEach(function (input) {
      if (input.files && input.files.length) { parts.push(said(box, input)); }
    });
    box.querySelector(".upload-said").textContent =
      parts.length ? parts.join("; ") : box.dataset.saidNone;
    box.querySelector("[data-upload-clear]").hidden = !parts.length;
  }

  function enhance(root) {
    root.querySelectorAll(".uploads:not([data-enhanced])").forEach(function (box) {
      box.setAttribute("data-enhanced", "");
      describe(box);
    });
  }

  document.addEventListener("change", function (event) {
    var box = event.target.closest && event.target.closest(".uploads");
    if (box && event.target.type === "file") { describe(box); }
  });
  document.addEventListener("click", function (event) {
    var clear = event.target.closest("[data-upload-clear]");
    if (!clear) { return; }
    var box = clear.closest(".uploads");
    box.querySelectorAll('input[type="file"]').forEach(function (input) { input.value = ""; });
    describe(box);
  });
  document.addEventListener("htmx:load", function (event) { enhance(event.target); });

  // While the chosen files are sent, the form's foot counts them (#11): the
  // task begins only once the last byte has arrived, and a spinner alone
  // said nothing for however long that took. htmx reports the answer's
  // download the same way, but only once the answer has begun, which is
  // after the last byte was sent - when "sent" is already true.
  var MEGABYTE = 1024 * 1024;

  function chosenIn(form) {
    return Array.prototype.some.call(
      form.querySelectorAll('input[type="file"]'),
      function (input) { return input.files && input.files.length > 0; }
    );
  }

  document.addEventListener("htmx:xhr:progress", function (event) {
    var form = event.target.closest && event.target.closest("form");
    var line = form && form.querySelector(".sending");
    var detail = event.detail;
    if (!line || !detail.lengthComputable || !chosenIn(form)) { return; }
    line.hidden = false;
    line.textContent = detail.loaded >= detail.total
      ? line.dataset.saidSent
      : filled(line.dataset.saidSending, {
          sent: (detail.loaded / MEGABYTE).toFixed(1),
          total: (detail.total / MEGABYTE).toFixed(1),
        });
  });

  document.addEventListener("htmx:afterRequest", function (event) {
    var line = event.target.querySelector && event.target.querySelector(".sending");
    if (!line) { return; }
    line.hidden = true;
  });
  enhance(document);
})();
