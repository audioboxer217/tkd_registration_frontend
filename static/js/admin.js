$(document).ready(function() {
  var table = $('#entries').DataTable({
    reponsive: true,
    searchPanes: {
      cascadePanes: true,
      columns: [3,4],
      initCollapsed: true,
    },
    columnDefs: [
      {
        "targets": 1,
        "orderable": false
      },
      {
        "targets": 2,
        "orderable": false
      },
      {
        "targets": 5,
        "orderable": false
      }
    ],
  });
  table.searchPanes.container().prependTo(table.table().container());
  table.searchPanes.resizePanes();
});
