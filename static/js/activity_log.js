// static/js/activity_log.js
// Activity Log page script
// Initializes DataTable with server-side processing, updates summary cards,
// and handles filters and export actions.

// Format duration: convert seconds to HH:MM:SS format
function formatDuration(seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  return String(hours).padStart(2, '0') + ':' + String(minutes).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
}

// Format hours to HH:MM format
function formatHours(hours) {
  return formatDuration(hours * 3600);
}

function fileOrAppName(row) {
  const fileName = String(row['File Name'] || '').trim();
  const appName = String(row['App Name'] || '').trim();
  const baseName = fileName.split(/[\\/]/).pop();
  const hasFileExtension = /\.[a-z0-9]{1,8}$/i.test(baseName);

  if (baseName && hasFileExtension) {
    return baseName;
  }

  return appName || baseName || 'Unknown Window';
}

function currentFilters(extra = {}) {
  const filters = {
    project: $('#project-filter').val(),
    date_filter: $('#date-filter').val(),
    ...extra
  };

  if (filters.date_filter === 'custom') {
    filters.date_start = $('#date-start').val() || '';
    filters.date_end = $('#date-end').val() || '';
  }

  return filters;
}

$(document).ready(function () {
  // Initialize DataTable
  const table = $('#activity-table').DataTable({
    processing: true,
    serverSide: true,
    ajax: {
      url: '/api/activity-data',
      data: function (d) {
        Object.assign(d, currentFilters());
      }
    },
    columns: [
      { data: 'Activity Category' },
      {
        data: null,
        render: function (data, type, row) {
          const taskName = ActivityProcessor.deriveTaskName(row);
          return ActivityProcessor.normalizeProjectName(row['Project Name'], taskName);
        }
      },
      {
        data: null,
        render: function (data, type, row) {
          return fileOrAppName(row);
        }
      },
      { data: 'Start Time' },
      { data: 'End Time' },
      { data: 'Duration', render: function (data) { return formatDuration(parseFloat(data)); } }
    ],
    order: [[3, 'desc']], // default sort by Start Time desc
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
      data: currentFilters({ draw: 1, start: 0, length: 0 }),
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
      data: currentFilters({ project: 'All', draw: 1, start: 0, length: 1000 }),
      success: function (resp) {
        const projects = new Set();
        resp.data.forEach(row => {
          if (!ActivityProcessor.isUnassignedActivity(row)) {
            projects.add(row['Project Name']);
          }
        });
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
    loadSummary();
  });

  $('#date-start, #date-end').on('change', function () {
    if ($('#date-filter').val() === 'custom') {
      table.ajax.reload();
      loadSummary();
    }
  });

  // Export buttons
  $('#export-csv').on('click', function () {
    const params = new URLSearchParams(currentFilters({ format: 'csv' }));
    window.location.href = '/export/activity?' + params.toString();
  });

  $('#export-excel').on('click', function () {
    const params = new URLSearchParams(currentFilters({ format: 'excel' }));
    window.location.href = '/export/activity?' + params.toString();
  });
});
