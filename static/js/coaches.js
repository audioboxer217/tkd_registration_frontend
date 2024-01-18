$(document).ready(function() {
  var table = $('#coaches').DataTable({
    reponsive: true,
    searchPanes: {
      cascadePanes: true,
      columns: [1],
    },
  });
  table.searchPanes.container().prependTo(table.table().container());
  table.searchPanes.resizePanes();
});
