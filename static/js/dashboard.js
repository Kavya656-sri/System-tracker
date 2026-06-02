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

document.addEventListener('DOMContentLoaded', function () {
  if (page === 'overview') {
    // Populate cards
    document.getElementById('totalSessions').textContent = totalSessions;
    document.getElementById('productiveSessions').textContent = productiveSessions;
    document.getElementById('idleSessions').textContent = idleSessions;
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

    // Application Usage Bar Chart (horizontal bar)
    const ctxBar = document.getElementById('appBarChart').getContext('2d');
    new Chart(ctxBar, {
      type: 'bar',
      data: {
        labels: barLabels,
        datasets: [{
          label: 'Total Duration (s)',
          data: barValues,
          backgroundColor: 'rgba(54, 162, 235, 0.6)',
          borderColor: 'rgba(54, 162, 235, 1)',
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
                const full = barFullLabels[idx] || '';
                return `${full}: ${context.parsed.x}s`;
              }
            }
          },
          legend: { display: false }
        },
        scales: {
          x: { title: { display: true, text: 'Duration (seconds)' } },
          y: { ticks: { autoSkip: false } }
        }
      }
    });

    // Recent Activities Table
    const tbody = document.getElementById('recentTableBody');
    recentActivities.forEach(rec => {
      const tr = document.createElement('tr');
      const tdProj = document.createElement('td'); tdProj.textContent = rec['Project Name'];
      const tdApp = document.createElement('td'); tdApp.textContent = rec['App Name'];
      const tdStart = document.createElement('td'); tdStart.textContent = rec['Start Time'];
      const tdDur = document.createElement('td'); tdDur.textContent = formatDuration(parseFloat(rec['Duration']));
      tr.append(tdProj, tdApp, tdStart, tdDur);
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

        // Productive vs Idle Doughnut Chart
        const ctxDoughnut = document.getElementById('prodIdleChart').getContext('2d');
        new Chart(ctxDoughnut, {
          type: 'doughnut',
          data: {
            labels: ['Productive Time (hrs)', 'Idle Time (hrs)'],
            datasets: [{
              data: [data.summary.productive_hours, data.summary.idle_hours],
              backgroundColor: ['#2ec4b6', '#e71d36']
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
            labels: data.project_breakdown.map(p => p['Project Name']),
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
            labels: data.top_apps.map(a => a['App Name']),
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
        // Productivity Trend Line Chart
        const ctxTrend = document.getElementById('trendLineChart').getContext('2d');
        new Chart(ctxTrend, {
          type: 'line',
          data: {
            labels: data.trend.map(t => t['Date']),
            datasets: [{
              label: 'Productive Hours',
              data: data.trend.map(t => t['Hours']),
              borderColor: 'rgba(255, 99, 132, 1)',
              backgroundColor: 'rgba(255, 99, 132, 0.2)',
              borderWidth: 2,
              tension: 0.1,
              fill: true
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: 'Date' } },
              y: { title: { display: true, text: 'Hours' }, beginAtZero: true }
            }
          }
        });
      })
      .catch(err => console.error('Error fetching productivity data:', err));
  }
});
