$(document).ready(function() {
  var table = $('#competitors').DataTable({
    // columns: [
    //   { "data" : "Name" },
    //   { "data" : "Gender" },
    //   { "data" : "Belt" },
    //   { "data" : "Age" },
    //   { "data" : "Weight" },
    //   { "data" : "School" },
    //   { "data" : "Events" }
    // ],
    reponsive: true,
    searchPanes: {
      cascadePanes: true,
      columns: [1,2,4],
      panes: [
        {
          header: 'Age Group',
          options: [
            {
              label: 'Dragon',
              value: function(rowData, rowIdx){
                  return rowData[3] <= 7;
              }
            },
            {
              label: 'Tiger',
              value: function(rowData, rowIdx){
                  return rowData[3] == 8 || rowData[3] == 9;
              }
            },
            {
              label: 'Youth',
              value: function(rowData, rowIdx){
                  return rowData[3] == 10 || rowData[3] == 11;
              }
            },
            {
              label: 'Cadet',
              value: function(rowData, rowIdx){
                  return rowData[3] >= 12 && rowData[3] <= 14;
              }
            },
            {
              label: 'Junior',
              value: function(rowData, rowIdx){
                  return rowData[3] == 15 || rowData[3] == 16;
              }
            },
            {
              label: 'Senior',
              value: function(rowData, rowIdx){
                  return rowData[3] >= 17 && rowData[3] <= 19;
              }
            },
            {
              label: 'Ultra',
              value: function(rowData, rowIdx){
                  return rowData[3] >= 20;
              }
            },
          ]
        },
        {
          header: 'Events',
          options: [
            {
              label: 'Sparring - World Class',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('sparring-wc')
              }
            },
            {
              label: 'Sparring - Grass Roots',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('sparring-gr')
              }
            },
            {
              label: 'Sparring - Color Belt',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('sparring')
              }
            },
            {
              label: 'Poomsae',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('poomsae')
              }
            },
            {
              label: 'Pair Poomsae',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('pair poomsae')
              }
            },
            {
              label: 'Team Poomsae',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('team poomsae')
              }
            },
            {
              label: 'Breaking',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('breaking')
              }
            },
            {
              label: 'Little Dragon Obstacle Course',
              value: function(rowData, rowIdx){
                events_arr = rowData[6].split(',').map(s => s.trim());
                return events_arr.includes('little_dragon')
              }
            },
          ]
        }
      ],
    },
  });
  table.searchPanes.container().prependTo(table.table().container());
  table.searchPanes.resizePanes();
});
