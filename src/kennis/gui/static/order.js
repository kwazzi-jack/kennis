// A setting that is an ordered list, as chips to drag (#670).
//
// **The text field is the setting and the chips are a way to write it.**
// The server draws both: the field, which is what the form posts and all
// there is without this script, and after it a hidden list of chips, one
// per value the list may hold. This shows the chips, hides the field, and
// on every change writes the field's value - the ticked chips' values in
// the order they stand, separated by spaces.
//
// A chip is moved by dragging it, or by its two buttons, so the keyboard
// can do what the mouse does; its tick box says whether it is in the list.
// Events are delegated from the document, because htmx replaces the
// section when it is saved or redrawn. Nothing here composes a sentence:
// every name and label is the server's.
(function () {
  var dragged = null;

  function fieldOf(list) {
    return document.getElementById(list.dataset.orderFor);
  }

  function write(list) {
    var field = fieldOf(list);
    if (!field) { return; }
    var values = [];
    list.querySelectorAll(".order-chip").forEach(function (chip) {
      var box = chip.querySelector("[data-order-include]");
      if (box && box.checked) {
        chip.removeAttribute("data-left-out");
        values.push(chip.dataset.value);
      } else {
        chip.setAttribute("data-left-out", "");
      }
    });
    field.value = values.join(" ");
  }

  function show(root) {
    root.querySelectorAll(".order-chips").forEach(function (list) {
      var field = fieldOf(list);
      if (!field) { return; }
      list.hidden = false;
      field.hidden = true;
      var hint = list.nextElementSibling;
      if (hint && hint.matches(".order-hint")) { hint.hidden = false; }
    });
  }

  function chipAt(target) {
    return target && target.closest ? target.closest(".order-chip") : null;
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-move]") : null;
    var chip = chipAt(button);
    if (!chip) { return; }
    var list = chip.parentNode;
    // The neighbour is what moves, either way: an element taken out of the
    // page and put back loses its focus, and the pressed button is in this
    // chip, where the reader will press it again.
    if (button.dataset.move === "earlier" && chip.previousElementSibling) {
      list.insertBefore(chip.previousElementSibling, chip.nextElementSibling);
    } else if (button.dataset.move === "later" && chip.nextElementSibling) {
      list.insertBefore(chip.nextElementSibling, chip);
    }
    write(list);
  });

  document.addEventListener("change", function (event) {
    if (!event.target.matches || !event.target.matches("[data-order-include]")) { return; }
    var chip = chipAt(event.target);
    if (chip) { write(chip.parentNode); }
  });

  document.addEventListener("dragstart", function (event) {
    var chip = chipAt(event.target);
    if (!chip) { return; }
    dragged = chip;
    chip.setAttribute("data-dragging", "");
    event.dataTransfer.effectAllowed = "move";
    // Firefox starts no drag without data.
    event.dataTransfer.setData("text/plain", chip.dataset.value);
  });

  document.addEventListener("dragover", function (event) {
    var over = chipAt(event.target);
    if (!dragged || !over || over.parentNode !== dragged.parentNode) { return; }
    event.preventDefault();
    if (over === dragged) { return; }
    var box = over.getBoundingClientRect();
    var after = event.clientX > box.left + box.width / 2;
    over.parentNode.insertBefore(dragged, after ? over.nextElementSibling : over);
  });

  document.addEventListener("drop", function (event) {
    if (dragged && chipAt(event.target)) { event.preventDefault(); }
  });

  document.addEventListener("dragend", function () {
    if (!dragged) { return; }
    dragged.removeAttribute("data-dragging");
    write(dragged.parentNode);
    dragged = null;
  });

  show(document);
  document.addEventListener("htmx:afterSwap", function () { show(document); });
})();
