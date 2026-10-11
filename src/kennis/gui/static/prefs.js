// This window's preferences: apply a choice the moment it is made.
//
// **The server renders every choice and this only handles the change.**
// Each is a cookie on the request, so `<html data-NAME>` is right in the
// first byte; read from browser storage after paint, every page would
// draw in the defaults and then repaint. This writes the attribute so
// the page changes now, and the cookie so the next page is drawn that
// way.
//
// Every control marked `data-pref` is one: its `name` is the attribute,
// the cookie and the form field at once. With this script nothing waits
// for Save, so the button is hidden; without it, Save posts the form.
//
// The cookie's attributes are this file's: `path=/` so it is not scoped
// to the settings page, and `samesite=strict` for the reason the token
// cookie has it. Nothing here composes a sentence.
(function () {
  var YEAR = 31536000;

  document.querySelectorAll(".prefs-save").forEach(function (button) {
    button.hidden = true;
  });

  document.addEventListener("change", function (event) {
    var control = event.target;
    if (!control.matches || !control.matches("[data-pref]")) { return; }
    document.documentElement.dataset[control.name] = control.value;
    document.cookie =
      control.name + "=" + control.value + "; path=/; max-age=" + YEAR + "; samesite=strict";
  });
})();
