// Shared display-side activity processing for Flask pages.
// Converts raw captured window/file names into meaningful task labels before rendering.
(function (window) {
  console.log("ACTIVITY PROCESSOR RUNNING");

  const unassignedKeywords = [
    'system idle',
    'system sleep',
    'search',
    'snipping tool overlay',
    'snipping tool',
    'unknown window',
    'program manager',
    'task switching',
    'file explorer',
    'system tray overflow window'
  ];

  const browserKeywords = [
    'chrome',
    'google chrome',
    'edge',
    'microsoft edge',
    'firefox'
  ];

  const unrelatedBrowserKeywords = [
    'youtube',
    'netflix',
    'instagram',
    'facebook',
    'shopping',
    'amazon',
    'flipkart',
    'spotify'
  ];

  const defaultProjectName = 'productivity Tracker';
  const genericProjectNames = [
    'browser work',
    'chrome work',
    'edge work',
    'unknown project',
    'unassigned activities',
    'idle'
  ];

  const taskRules = [
    {
      keywords: ['overview dashboard', 'live dashboard', 'dashboard development'],
      task: 'Dashboard Development'
    },
    {
      keywords: ['email verification', 'email_verification'],
      task: 'Email Verification Module'
    },
    {
      keywords: ['email sender', 'email_sender', 'outlook', 'inbox', 'gmail'],
      task: 'Email Automation Module'
    },
    {
      keywords: ['task scheduler auto start', 'auto start', 'autostart', 'startup'],
      task: 'Auto Start Feature'
    }
  ];

  function clean(value) {
    return String(value ?? '').replace(/\u200b/g, '').trim();
  }

  function lower(value) {
    return clean(value).toLowerCase();
  }

  function hasAny(text, keywords) {
    const value = lower(text);
    return keywords.some(keyword => value.includes(keyword));
  }

  function isBrowserActivity(value) {
    return hasAny(value, browserKeywords);
  }

  function isUnrelatedBrowser(value) {
    return hasAny(value, unrelatedBrowserKeywords);
  }

  function normalizeProjectName(value, taskName = '') {
    const project = clean(value);
    const normalized = lower(project);
    const task = lower(taskName);

    if (genericProjectNames.includes(normalized)) {
      return task && task !== 'unassigned activity' ? defaultProjectName : 'Unassigned Activities';
    }

    return project || defaultProjectName;
  }

  function isUnassignedActivity(rowOrText) {
    const text = typeof rowOrText === 'object'
      ? [rowOrText['Activity Category'], rowOrText['Project Name'], rowOrText.Project, rowOrText['App Name'], rowOrText.task, rowOrText.app].join(' ')
      : rowOrText;
    const normalized = lower(text);

    if (normalized.includes('unassigned activities') || normalized === 'idle') {
      return true;
    }

    return unassignedKeywords.some(keyword => normalized.includes(keyword));
  }

  function ruleTaskName(...values) {
    const text = values.map(clean).join(' ').toLowerCase();
    const matched = taskRules.find(rule => rule.keywords.some(keyword => text.includes(keyword)));
    return matched ? matched.task : '';
  }

  function isRuleBasedTaskName(value) {
    return taskRules.some(rule => rule.task === clean(value));
  }

  function humanize(value) {
    let text = clean(value).split(' - ')[0] || clean(value);
    text = text.replace(/\.[A-Za-z0-9]+$/, '');
    text = text.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();

    if (!text) {
      return 'Development Task';
    }

    return text.replace(/\w\S*/g, word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
  }

  function deriveTaskName(rowOrText) {
    const row = typeof rowOrText === 'object' ? rowOrText : {};
    const rawText = typeof rowOrText === 'object' ? '' : rowOrText;
    const app = clean(row['App Name'] || row.app || rawText);
    const task = clean(row.task || row['Task'] || row['AI Task Name'] || '');
    const sourceTask = clean(row.source_task || row['File Name'] || row.file_name || task);

    const ruleName = ruleTaskName(app, task, sourceTask);
    if (ruleName) {
      return ruleName;
    }

    if (isUnassignedActivity(rowOrText)) {
      return 'Unassigned Activity';
    }

    if (isBrowserActivity(app) && !isUnrelatedBrowser(app)) {
      return clean(task || sourceTask || app);
    }

    const normalizedTask = humanize(task || sourceTask || app).replace(/(?:\s+Module)+$/i, ' Module');
    return normalizedTask.toLowerCase().endsWith(' module') ? normalizedTask : `${normalizedTask} Module`;
  }

  function parseDurationSeconds(value) {
    const parts = clean(value || '00:00').split(':').map(part => Number(part) || 0);
    if (parts.length >= 3) {
      return (parts[0] * 3600) + (parts[1] * 60) + parts[2];
    }
    if (parts.length >= 2) {
      return (parts[0] * 3600) + (parts[1] * 60);
    }
    return parts[0] || 0;
  }

  function formatDurationSeconds(seconds) {
    const safeSeconds = Math.max(0, Math.round(seconds || 0));
    const hours = Math.floor(safeSeconds / 3600);
    const mins = Math.floor((safeSeconds % 3600) / 60);
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
  }

  function formatDurationWithSeconds(seconds) {
    const safeSeconds = Math.max(0, Math.round(seconds || 0));
    const hours = Math.floor(safeSeconds / 3600);
    const mins = Math.floor((safeSeconds % 3600) / 60);
    const secs = safeSeconds % 60;
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function deriveDisplayDate(row) {
    const directDate = clean(row.date || row.Date);

    if (directDate) {
      return directDate;
    }

    const rawDateTime = clean(row['Start Time'] || row.start_time || row.startTime);

    if (!rawDateTime) {
      const today = new Date();
      return [
        String(today.getDate()).padStart(2, '0'),
        String(today.getMonth() + 1).padStart(2, '0'),
        today.getFullYear()
      ].join('-');
    }

    const parsed = new Date(rawDateTime);

    if (!Number.isNaN(parsed.getTime())) {
      return [
        String(parsed.getDate()).padStart(2, '0'),
        String(parsed.getMonth() + 1).padStart(2, '0'),
        parsed.getFullYear()
      ].join('-');
    }

    const match = rawDateTime.match(/^(\d{4})-(\d{2})-(\d{2})/);

    if (match) {
      return `${match[3]}-${match[2]}-${match[1]}`;
    }

    return rawDateTime.split(/\s+/)[0] || [
      String(new Date().getDate()).padStart(2, '0'),
      String(new Date().getMonth() + 1).padStart(2, '0'),
      new Date().getFullYear()
    ].join('-');
  }

  function processTaskRows(rows) {
    const grouped = new Map();

    (rows || []).forEach(row => {
      const processedTask = deriveTaskName(row);

      if (!processedTask || processedTask === 'Unassigned Activity') {
        return;
      }

      const project = normalizeProjectName(row.project || row.Project || row['Project Name'], processedTask);
      const date = deriveDisplayDate(row);
      const status = clean(row.status || row.Status || 'In Progress');
      const key = `${date}|||${project}|||${processedTask}|||${status}`;
      const current = grouped.get(key) || {
        ...row,
        date,
        project,
        task: processedTask,
        source_task: clean(row.source_task || row.task || row['App Name'] || processedTask),
        status,
        duration: '00:00:00',
        _seconds: 0
      };

      current._seconds += parseDurationSeconds(row.duration || row.Duration);
      current.duration = formatDurationSeconds(current._seconds);
      grouped.set(key, current);
    });

    return Array.from(grouped.values()).map(row => {
      const { _seconds, ...publicRow } = row;
      return publicRow;
    });
  }

  function processUnassignedRows(rows) {
    return (rows || []).map(row => {
      const originalName = clean(row.raw_app || row.app || row['App Name'] || row.task || 'Unknown Window');
      const processedName = deriveTaskName(row);
      const displayName = isRuleBasedTaskName(processedName) ? processedName : originalName;

      return {
        ...row,
        date: deriveDisplayDate(row),
        app: displayName,
        task: displayName,
        duration: formatDurationWithSeconds(parseDurationSeconds(row.duration || row.Duration)),
        raw_app: originalName
      };
    });
  }

  function processEmailPayload(tasks, unassigned) {
    const processedTasks = processTaskRows(tasks || []);
    const remainingUnassigned = [];

    (unassigned || []).forEach(row => {
      const processedTask = deriveTaskName(row);

      if (isRuleBasedTaskName(processedTask)) {
        processedTasks.push({
          date: deriveDisplayDate(row),
          project: normalizeProjectName(row.project || row.Project || row['Project Name'], processedTask),
          task: processedTask,
          source_task: clean(row.task || row.app || row['App Name'] || processedTask),
          status: clean(row.status || row.Status || 'In Progress'),
          duration: clean(row.duration || row.Duration || '00:00:00'),
          activity_ids: row.activity_ids || []
        });
      } else {
        const originalName = clean(row.raw_app || row.app || row['App Name'] || row.task || 'Unknown Window');
        remainingUnassigned.push({
          ...row,
          date: deriveDisplayDate(row),
          app: originalName,
          task: originalName,
          duration: formatDurationWithSeconds(parseDurationSeconds(row.duration || row.Duration)),
          raw_app: originalName
        });
      }
    });

    return {
      taskRows: processTaskRows(processedTasks),
      unassignedRows: remainingUnassigned
    };
  }

  window.ActivityProcessor = {
    deriveTaskName,
    processTaskRows,
    processUnassignedRows,
    processEmailPayload,
    normalizeProjectName,
    isUnassignedActivity,
    isBrowserActivity,
    isUnrelatedBrowser
  };
})(window);
