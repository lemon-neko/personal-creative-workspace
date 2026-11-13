(() => {
  const text = (tag, value, className = '') => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  };

  const values = (form, name) => Array.from(form.querySelectorAll(`[name="${name}"]`)).map((node) => node.value.trim());
  const value = (form, name) => form.elements.namedItem(name)?.value?.trim?.() || '';
  const lines = (input) => input.split(/\r?\n/).map((row) => row.trim()).filter(Boolean);

  const addBullets = (target, bullets) => {
    if (!bullets.length) return;
    const list = document.createElement('ul');
    bullets.forEach((bullet) => list.append(text('li', bullet)));
    target.append(list);
  };

  const addEntry = (target, lead, role, years, subline, bullets, description = '') => {
    if (!lead && !role && !subline && !bullets.length && !description) return;
    const entry = document.createElement('div');
    entry.className = 'ats-entry';
    const heading = document.createElement('div');
    heading.className = 'ats-entry-heading';
    heading.append(text('strong', lead || subline));
    heading.append(text('b', role || ''));
    heading.append(text('span', years || ''));
    entry.append(heading);
    if (subline && subline !== lead) entry.append(text('p', subline, 'ats-subline'));
    addBullets(entry, bullets);
    if (description) entry.append(text('p', description));
    target.append(entry);
  };

  const addProjectEntry = (
    target,
    lead,
    role,
    years,
    summary,
    techStack,
    responsibilities,
    legacyDescription,
  ) => {
    const hasStructure = Boolean(summary || techStack.length || responsibilities.length);
    if (!lead && !role && !years && !hasStructure && !legacyDescription.length) return;
    const entry = document.createElement('div');
    entry.className = 'ats-entry resume-project-entry';
    const heading = document.createElement('div');
    heading.className = 'ats-entry-heading resume-project-heading';
    heading.append(text('strong', lead));
    heading.append(text('b', role));
    heading.append(text('span', years));
    entry.append(heading);

    const projectBlock = (className, label, content) => {
      const block = document.createElement('div');
      block.className = `resume-project-block ${className}`;
      block.append(text('strong', label));
      if (Array.isArray(content)) addBullets(block, content);
      else block.append(text('p', content));
      entry.append(block);
    };
    if (hasStructure) {
      if (summary) projectBlock('resume-project-summary', '项目简介', summary);
      if (techStack.length) projectBlock('resume-project-tech', '技术栈', techStack.join(' · '));
      if (responsibilities.length) {
        projectBlock('resume-project-responsibilities', '个人职责', responsibilities);
      }
    } else {
      addBullets(entry, legacyDescription);
    }
    target.append(entry);
  };

  const displayYears = (input) => (input || '').replace(/[–—]/g, '-').trim();

  const groupYears = (positions) => {
    const values = positions.map((position) => displayYears(position.years)).filter(Boolean);
    if (!values.length) return '';
    if (values.length === 1) return values[0];
    const dates = values.flatMap((item) => item.match(/\d{4}(?:[./-]\d{1,2})?/g) || []);
    if (!dates.length) return [...new Set(values)].join(' / ');
    const start = [...dates].sort()[0];
    const end = values.some((item) => item.includes('至今')) ? '至今' : [...dates].sort().at(-1);
    return start === end ? start : `${start} - ${end}`;
  };

  const groupDescription = (items) => {
    const intro = [];
    const groups = [];
    let current = null;
    items.forEach((item) => {
      if (/^[^。；;]{1,24}\s+[-–—]\s+[^。；;]{1,60}$/.test(item)) {
        current = { title: item.replace(/[–—]/g, '-'), bullets: [] };
        groups.push(current);
      } else if (current) {
        current.bullets.push(item);
      } else {
        intro.push(item);
      }
    });
    return { intro, groups };
  };

  const groupWorkRows = (rows) => {
    const groups = [];
    const lookup = new Map();
    rows.forEach((source, index) => {
      const row = { ...source, years: displayYears(source.years) };
      const description = groupDescription(row.description);
      row.descriptionIntro = description.intro;
      row.descriptionGroups = description.groups;
      const key = row.company ? row.company.toLocaleLowerCase() : `__position_${index}`;
      let group = lookup.get(key);
      if (!group) {
        group = { company: row.company || '工作经历', locations: [], positions: [] };
        lookup.set(key, group);
        groups.push(group);
      }
      if (row.location && !group.locations.includes(row.location)) group.locations.push(row.location);
      group.positions.push(row);
    });
    return groups.map((group) => ({
      ...group,
      location: group.locations.join(' / '),
      years: groupYears(group.positions),
    }));
  };

  const addWorkGroups = (target, rows) => {
    const meaningfulRows = rows.filter((row) => (
      row.title || row.company || row.location || row.years || row.description.length
    ));
    groupWorkRows(meaningfulRows).forEach((group) => {
      const employer = document.createElement('div');
      employer.className = 'resume-employer';
      const employerHeading = document.createElement('div');
      employerHeading.className = 'resume-employer-heading';
      employerHeading.append(text('strong', group.company));
      employerHeading.append(text('span', group.location, 'resume-employer-location'));
      employerHeading.append(text('span', group.years, 'resume-employer-years'));
      employer.append(employerHeading);
      const positionList = document.createElement('div');
      positionList.className = 'resume-position-list';
      group.positions.forEach((position) => {
        const node = document.createElement('div');
        node.className = 'resume-position';
        const heading = document.createElement('div');
        heading.className = 'resume-position-heading';
        heading.append(text('strong', position.title || '岗位'));
        const showPositionYears = group.positions.length > 1 && position.years !== group.years;
        heading.append(text('span', showPositionYears ? position.years : ''));
        node.append(heading);
        if (position.descriptionGroups.length) {
          addBullets(node, position.descriptionIntro);
          const responsibilityList = document.createElement('div');
          responsibilityList.className = 'resume-responsibility-list';
          position.descriptionGroups.forEach((responsibility) => {
            const responsibilityNode = document.createElement('div');
            responsibilityNode.className = 'resume-responsibility';
            responsibilityNode.append(text('strong', responsibility.title));
            addBullets(responsibilityNode, responsibility.bullets);
            responsibilityList.append(responsibilityNode);
          });
          node.append(responsibilityList);
        } else {
          addBullets(node, position.description);
        }
        positionList.append(node);
      });
      employer.append(positionList);
      target.append(employer);
    });
  };

  const section = (title) => {
    const node = document.createElement('section');
    node.append(text('h2', title));
    return node;
  };

  const contactItem = (iconName, contactValue) => {
    const item = document.createElement('span');
    item.className = 'resume-contact-item';
    item.dataset.resumeContact = iconName;
    const template = document.querySelector(`[data-resume-icon-template="${iconName}"]`);
    const icon = template?.content?.firstElementChild?.cloneNode(true);
    if (icon) item.append(icon);
    item.append(text('span', contactValue, 'resume-contact-text'));
    return item;
  };

  const templateOrder = {
    china_single_photo: ['summary', 'education', 'skills', 'work_experience', 'projects', 'self_evaluation'],
  };

  const fitPreview = (form) => {
    const frame = form?.querySelector('[data-resume-preview-frame]');
    const canvas = frame?.querySelector('[data-resume-preview-sheet]');
    if (!frame || !canvas) return;
    const available = Math.max(1, frame.clientWidth);
    const naturalWidth = canvas.offsetWidth || 794;
    const scale = Math.min(1, available / naturalWidth);
    canvas.style.transform = `scale(${scale})`;
    frame.style.height = `${Math.ceil(canvas.offsetHeight * scale)}px`;
    const label = form.querySelector('[data-resume-preview-scale]');
    if (label) label.textContent = `${Math.round(scale * 100)}%`;
  };

  const renderPreview = (form) => {
    if (!form) return;
    const sheet = form.querySelector('.ats-sheet');
    if (!sheet) return;
    const templateKey = value(form, 'template_key') || sheet.dataset.resumeTemplate || 'ats_single';
    sheet.dataset.resumeTemplate = templateKey;
    sheet.classList.toggle('resume-template-china_single_photo', templateKey === 'china_single_photo');
    sheet.classList.toggle('resume-template-ats_single', templateKey === 'ats_single');
    const toolbarTemplate = form.querySelector('.resume-preview-toolbar div span');
    if (toolbarTemplate) {
      toolbarTemplate.textContent = `${templateKey === 'china_single_photo' ? '技术社招版' : 'ATS 基础版'} · 国内版`;
    }
    const photo = sheet.querySelector('.ats-photo')?.cloneNode(true);
    const personalName = value(form, 'personal_name') || '姓名';
    const header = document.createElement('header');
    const identity = document.createElement('div');
    identity.className = 'ats-identity';
    identity.append(text('h1', personalName));
    const role = value(form, 'personal_title') || value(form, 'target_role');
    const appendContact = (items, className = '', withIcons = false) => {
      const contactValues = items.filter((item) => (
        withIcons ? Boolean(item?.value) : Boolean(item)
      ));
      if (!contactValues.length) return;
      const contact = document.createElement('p');
      contact.className = `ats-contact ${className}`.trim();
      contactValues.forEach((item) => contact.append(
        withIcons ? contactItem(item.icon, item.value) : text('span', item),
      ));
      identity.append(contact);
    };
    if (templateKey === 'china_single_photo') {
      appendContact(
        [
          { icon: 'phone', value: value(form, 'personal_phone') },
          { icon: 'mail', value: value(form, 'personal_email') },
          { icon: 'world', value: value(form, 'personal_website') },
          { icon: 'brand-github', value: value(form, 'personal_github') },
        ],
        'ats-contact-primary',
        true,
      );
      const experience = value(form, 'personal_experience_years');
      const age = value(form, 'personal_age');
      const institution = values(form, 'education_institution')[0] || '';
      const degree = values(form, 'education_degree')[0] || '';
      appendContact([
        { icon: 'briefcase', value: experience ? `${experience}${experience.includes('经验') ? '' : '经验'}` : '' },
        { icon: 'target', value: role },
        { icon: 'school', value: institution ? `${institution}${degree ? `（${degree}）` : ''}` : '' },
        { icon: 'map-pin', value: value(form, 'personal_location') },
        { icon: 'calendar-user', value: age ? `${age}岁` : '' },
      ], 'ats-contact-secondary', true);
    } else {
      if (role) identity.append(text('p', role, 'ats-role'));
      appendContact(['personal_phone', 'personal_email', 'personal_experience_years', 'personal_age', 'personal_location', 'personal_website', 'personal_github'].map((name) => value(form, name)));
    }
    header.append(identity);
    if (photo) header.append(photo);
    sheet.classList.toggle('has-photo', Boolean(photo));
    const fragment = document.createDocumentFragment();
    fragment.append(header);

    const selectedSections = Array.from(form.querySelectorAll('[name="visible_sections"]:checked'))
      .map((input) => ({
        key: input.value,
        title: value(form, `section_title_${input.value}`) || input.value,
        order: Number(value(form, `section_order_${input.value}`) || 0),
      }))
      .sort((left, right) => {
        const order = templateOrder[templateKey];
        if (!order) return left.order - right.order;
        return order.indexOf(left.key) - order.indexOf(right.key);
      });

    selectedSections.forEach(({ key, title }) => {
      if (key === 'summary') {
        const summary = value(form, 'summary');
        if (summary) {
          const node = section(title);
          node.dataset.sectionKey = key;
          node.className = 'resume-section-summary';
          node.append(text('p', summary));
          fragment.append(node);
        }
      }
      if (key === 'work_experience') {
        const titles = values(form, 'work_title');
        const companies = values(form, 'work_company');
        const locations = values(form, 'work_location');
        const years = values(form, 'work_years');
        const descriptions = values(form, 'work_description');
        const node = section(title);
        node.dataset.sectionKey = key;
        addWorkGroups(node, titles.map((jobTitle, index) => ({
          title: jobTitle,
          company: companies[index] || '',
          location: locations[index] || '',
          years: years[index] || '',
          description: lines(descriptions[index] || ''),
        })));
        if (node.children.length > 1) fragment.append(node);
      }
      if (key === 'education') {
        const institutions = values(form, 'education_institution');
        const degrees = values(form, 'education_degree');
        const years = values(form, 'education_years');
        const descriptions = values(form, 'education_description');
        const node = section(title);
        node.dataset.sectionKey = key;
        institutions.forEach((institution, index) => addEntry(
          node,
          institution,
          degrees[index] || '',
          years[index] || '',
          '',
          [],
          descriptions[index] || '',
        ));
        if (node.children.length > 1) fragment.append(node);
      }
      if (key === 'projects') {
        const node = section(title);
        node.dataset.sectionKey = key;
        form.querySelectorAll('[name="project_ids"]:checked').forEach((checkbox) => {
          const id = checkbox.value;
          addProjectEntry(
            node,
            value(form, `project_name_${id}`),
            value(form, `project_role_${id}`),
            value(form, `project_years_${id}`),
            value(form, `project_summary_${id}`),
            lines(value(form, `project_tech_stack_${id}`).replace(/[，,；;]/g, '\n')),
            lines(value(form, `project_responsibilities_${id}`)),
            lines(value(form, `project_description_${id}`)),
          );
        });
        if (node.children.length > 1) fragment.append(node);
      }
      if (key === 'skills') {
        const skills = lines(value(form, 'skills'));
        if (skills.length) {
          const node = section(title);
          node.dataset.sectionKey = key;
          node.className = 'resume-section-skills';
          const list = document.createElement('ul');
          list.className = 'ats-skill-list';
          skills.forEach((skill) => list.append(text('li', skill)));
          node.append(list);
          fragment.append(node);
        }
      }
      if (key === 'self_evaluation') {
        const bullets = lines(value(form, 'self_evaluation'));
        if (bullets.length) {
          const node = section(title);
          node.dataset.sectionKey = key;
          addBullets(node, bullets);
          fragment.append(node);
        }
      }
    });
    sheet.replaceChildren(fragment);
    window.requestAnimationFrame(() => fitPreview(form));
  };

  const addRow = (kind) => {
    const template = document.getElementById(`resume-${kind}-template`);
    const target = document.getElementById(`resume-${kind}-rows`);
    if (template && target) {
      target.append(template.content.cloneNode(true));
      renderPreview(target.closest('form'));
    }
  };
  document.querySelectorAll('[data-resume-add]').forEach((button) => {
    button.addEventListener('click', () => addRow(button.dataset.resumeAdd));
  });
  document.querySelectorAll('.resume-editor-layout').forEach((form) => {
    let renderFrame = 0;
    const schedule = () => {
      window.cancelAnimationFrame(renderFrame);
      renderFrame = window.requestAnimationFrame(() => renderPreview(form));
    };
    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
    renderPreview(form);
    const previewFrame = form.querySelector('[data-resume-preview-frame]');
    if (previewFrame && 'ResizeObserver' in window) {
      const observer = new ResizeObserver(() => fitPreview(form));
      observer.observe(previewFrame);
    }
  });

  document.querySelectorAll('[data-resume-photo-input]').forEach((input) => {
    input.addEventListener('change', () => {
      const label = input.closest('form')?.querySelector('[data-resume-file-name]');
      if (label) label.textContent = input.files?.[0]?.name || 'PNG 或 JPEG';
    });
  });
})();
