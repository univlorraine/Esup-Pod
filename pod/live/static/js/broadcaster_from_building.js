$(document).ready(function () {
  let broadcastField = $("#id_broadcaster");

  $("#id_building").change(function () {
    $.ajax({
      url: "/live/ajax_calls/getbroadcastersfrombuiding/",
      type: "GET",
      dataType: "JSON",
      cache: false,
      data: {
        building: this.value,
      },

      success: (broadcasters) => {
        broadcastField.html("");

        if (broadcasters.length === 0) {
          console.log("pas de Broadcaster");
          broadcastField.prop("disabled", true);
          broadcastField.append(
            "<option value> Aucun broadcaster pour ce building</option>"
          );
        } else {
          broadcastField.prop("disabled", false);
          $.each(broadcasters, (key, value) => {
            broadcastField.append(
              '<option value="' + value.id + '">' + value.name + "</option>"
            );
          });
        }
      },
      error: () => {
        alert("une erreur s'est produite au chargement des broadcasters ...");
      },
    });
  });
});
