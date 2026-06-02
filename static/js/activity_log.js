// static/js/activity_log.js
// Activity Log page script
// Initializes DataTable with server-side processing, updates summary cards,
// and handles filters and export actions.

// Format duration: convert seconds to HH:MM format
function formatDuration(seconds) {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return String(hours).padStart(2, '0') + ':' + String(minutes).padStart(2, '0');
}

// Format hours to HH:MM format
function formatHours(hours) {
  return formatDuration(hours * 3600);
}

$(document).ready(function () {
  // Initialize DataTable
  const table = $('#activity-table').DataTable({
    processing: true,
    serverSide: true,
    ajax: {
      url: '/api/activity-data',
      data: function (d) {
        // Append filter parameters
        d.project = $('#project-filter').val();
        d.date_filter = $('#date-filter').val();
        if (d.date_filter === 'custom') {
          d.date_start = $('#date-start').val();
          d.date_end = $('#date-end').val();
        }
      }
    },
    columns: [
      { data: 'Project Name' },
      { data: 'App Name' },
      { data: 'Start Time' },
      { data: 'End Time' },
      { data: 'Duration', render: function (data) { return formatDuration(parseFloat(data)); } }
    ],
    order: [[2, 'desc']], // default sort by Start Time desc
    pageLength: 25,
    lengthMenu: [25, 50, 100, 200]
  });

  // Auto-refresh every 30 seconds
  setInterval(function () {
    table.ajax.reload(null, false); // false to keep current pagination
  }, 30000);

  // Load summary cards
  function loadSummary() {
    $.ajax({
      url: '/api/activity-data',
      data: { draw: 1, start: 0, length: 0 }, // no page data needed
      success: function (resp) {
        const summary = resp.summary;
        $('#total-records').text(summary.total_records);
        $('#total-work-time').text(formatHours(summary.total_work_time / 3600));
        $('#productive-time').text(formatHours(summary.productive_time / 3600));
        $('#idle-time').text(formatHours(summary.idle_time / 3600));
      }
    });
  }

  loadSummary();

  // Refresh summary when table is filtered/reloaded
  table.on('xhr', function () {
    loadSummary();
  });

  // Populate Project filter options dynamically based on available projects
  function populateProjectFilter() {
    $.ajax({
      url: '/api/activity-data',
      data: { draw: 1, start: 0, length: 0 },
      success: function (resp) {
        const projects = new Set();
        resp.data.forEach(row => projects.add(row['Project Name']));
        const $select = $('#project-filter');
        $select.empty().append('<option value="All">All</option>');
        Array.from(projects).sort().forEach(p => {
          $select.append(`<option value="${p}">${p}</option>`);
        });
      }
    });
  }

  populateProjectFilter();

  // Filter change handlers
  $('#project-filter, #date-filter').on('change', function () {
    // Show/hide custom date inputs
    if ($('#date-filter').val() === 'custom') {
      $('#custom-date-container').removeClass('d-none');
    } else {
      $('#custom-date-container').addClass('d-none');
    }
    table.ajax.reload();
  });

  $('#date-start, #date-end').on('change', function () {
    if ($('#date-filter').val() === 'custom') {
      table.ajax.reload();
    }
  });

  // Export buttons
  $('#export-csv').on('click', function () {
    const params = new URLSearchParams({
      format: 'csv',
      project: $('#project-filter').val(),
      date_filter: $('#date-filter').val()
    });
    if (params.get('date_filter') === 'custom') {
      params.append('date_start', $('#date-start').val() || '');
      params.append('date_end', $('#date-end').val() || '');
    }
    window.location.href = '/export/activity?' + params.toString();
  });

  $('#export-excel').on('click', function () {
    const params = new URLSearchParams({
      format: 'excel',
      project: $('#project-filter').val(),
      date_filter: $('#date-filter').val()
    });
    if (params.get('date_filter') === 'custom') {
      params.append('date_start', $('#date-start').val() || '');
      params.append('date_end', $('#date-end').val() || '');
    }
    window.location.href = '/export/activity?' + params.toString();
  });
});
