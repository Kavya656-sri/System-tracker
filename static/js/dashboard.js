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

document.addEventListener('DOMContentLoaded', function () {
  if (page === 'overview') {
    // Populate cards
    document.getElementById('totalSessions').textContent = totalSessions;
    document.getElementById('productiveSessions').textContent = productiveSessions;
    document.getElementById('idleSessions').textContent = idleSessions;
    document.getElementById('unassignedSessions').textContent = unassignedSessions;
    document.getElementById('productivityScore').textContent = productivityScore + '%';

    // Project Breakdown Pie Chart
    const ctxPie = document.getElementById('projectPieChart').getContext('2d');
    new Chart(ctxPie, {
      type: 'pie',
      data: {
        labels: pieLabels,
        datasets: [{
          data: pieValues,
          backgroundColor: ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc949', '#af7aa1', '#ff9da7', '#9c755f', '#bab0ab']
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'right' } }
      }
    });

    const topAppsList = document.getElementById('topApplicationsList');
    if (topAppsList) {
      const appNames = (barFullLabels || [])
        .filter(Boolean)
        .map(name => ActivityProcessor.deriveTaskName(name))
        .slice(0, 5);
      topAppsList.innerHTML = '';
      appNames.forEach(name => {
        const item = document.createElement('li');
        item.textContent = name;
        topAppsList.appendChild(item);
      });
    }

    // Recent Activities Table
    const tbody = document.getElementById('recentTableBody');
    recentActivities.forEach(rec => {
      const tr = document.createElement('tr');
      const tdCat = document.createElement('td'); tdCat.textContent = rec['Activity Category'] || 'Project Work';
      const taskName = ActivityProcessor.deriveTaskName(rec);
      const tdProj = document.createElement('td'); tdProj.textContent = ActivityProcessor.normalizeProjectName(rec['Project Name'], taskName);
      const tdApp = document.createElement('td'); tdApp.textContent = taskName;
      const tdStart = document.createElement('td'); tdStart.textContent = rec['Start Time'];
      const tdDur = document.createElement('td'); tdDur.textContent = formatDuration(parseFloat(rec['Duration']));
      tr.append(tdCat, tdProj, tdApp, tdStart, tdDur);
      tbody.appendChild(tr);
    });

  } else if (page === 'productivity') {
    // Fetch productivity data from the API endpoint
    fetch('/api/productivity')
      .then(response => response.json())
      .then(data => {
        // Populate Summary Cards
        document.getElementById('productivityScore').textContent = data.summary.productivity_score.toFixed(2) + '%';
        document.getElementById('totalWorkTime').textContent = formatHours(data.summary.total_work_hours);
        document.getElementById('productiveTime').textContent = formatHours(data.summary.productive_hours);
        document.getElementById('idleTime').textContent = formatHours(data.summary.idle_hours);

        // Category Doughnut Chart
        const ctxDoughnut = document.getElementById('prodIdleChart').getContext('2d');
        new Chart(ctxDoughnut, {
          type: 'doughnut',
          data: {
            labels: ['Project Work (hrs)', 'Unassigned Activities (hrs)', 'IDLE (hrs)'],
            datasets: [{
              data: [data.summary.productive_hours, data.summary.unassigned_hours || 0, data.summary.idle_hours],
              backgroundColor: ['#2ec4b6', '#f59e0b', '#e71d36']
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { position: 'bottom' }
            }
          }
        });

        // Project Productivity Breakdown Horizontal Bar Chart
        const ctxProj = document.getElementById('projectBarChart').getContext('2d');
        new Chart(ctxProj, {
          type: 'bar',
          data: {
            labels: data.project_breakdown.map(p => ActivityProcessor.normalizeProjectName(p['Project Name'], p['Project Name'])),
            datasets: [{
              label: 'Duration (hrs)',
              data: data.project_breakdown.map(p => p['Hours']),
              backgroundColor: 'rgba(75, 192, 192, 0.6)',
              borderColor: 'rgba(75, 192, 192, 1)',
              borderWidth: 1
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              tooltip: {
                callbacks: {
                  label: function (context) {
                    const idx = context.dataIndex;
                    const pct = data.project_breakdown[idx]['Percentage'];
                    return `${context.parsed.x.toFixed(2)} hrs (${pct}%)`;
                  }
                }
              },
              legend: { display: false }
            },
            scales: {
              x: { title: { display: true, text: 'Hours' } }
            }
          }
        });
        // Top Productive Applications Horizontal Bar Chart
        const ctxApps = document.getElementById('topAppChart').getContext('2d');
        new Chart(ctxApps, {
          type: 'bar',
          data: {
            labels: data.top_apps.map(a => ActivityProcessor.deriveTaskName(a)),
            datasets: [{
              label: 'Duration (hrs)',
              data: data.top_apps.map(a => a['Hours']),
              backgroundColor: 'rgba(153, 102, 255, 0.6)',
              borderColor: 'rgba(153, 102, 255, 1)',
              borderWidth: 1
            }]
          },
          options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              tooltip: {
                callbacks: {
                  label: function (context) {
                    const idx = context.dataIndex;
                    const pct = data.top_apps[idx]['Percentage'];
                    return `${context.parsed.x.toFixed(2)} hrs (${pct}%)`;
                  }
                }
              },
              legend: { display: false }
            },
            scales: {
              x: { title: { display: true, text: 'Hours' } }
            }
          }
        });
      })
      .catch(err => console.error('Error fetching productivity data:', err));
  }
});
