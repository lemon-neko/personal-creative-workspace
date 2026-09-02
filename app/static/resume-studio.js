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

  const addEntry = (target, title, years, subline, bullets, description = '') => {
    if (!title && !subline && !bullets.length && !description) return;
    const entry = document.createElement('div');
    entry.className = 'ats-entry';
    const heading = document.createElement('div');
    heading.append(text('strong', title || subline));
    if (years) heading.append(text('span', years));
    entry.append(heading);
    if (subline && subline !== title) entry.append(text('p', subline, 'ats-subline'));
    addBullets(entry, bullets);
    if (description) entry.append(text('p', description));
    target.append(entry);
  };

  const section = (title) => {
    const node = document.createElement('section');
    node.append(text('h2', title));
    return node;
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
    const photo = sheet.querySelector('.ats-photo')?.cloneNode(true);
    const personalName = value(form, 'personal_name') || '姓名';
    const header = document.createElement('header');
    const identity = document.createElement('div');
    identity.className = 'ats-identity';
    identity.append(text('h1', personalName));
    const role = value(form, 'personal_title') || value(form, 'target_role');
    if (role) identity.append(text('p', role, 'ats-role'));
    const contactValues = ['personal_email', 'personal_phone', 'personal_location', 'personal_website', 'personal_github']
      .map((name) => value(form, name)).filter(Boolean);
    if (contactValues.length) {
      const contact = document.createElement('p');
      contact.className = 'ats-contact';
      contactValues.forEach((item) => contact.append(text('span', item)));
      identity.append(contact);
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
      .sort((left, right) => left.order - right.order);

    selectedSections.forEach(({ key, title }) => {
      if (key === 'summary') {
        const summary = value(form, 'summary');
        if (summary) {
          const node = section(title);
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
        titles.forEach((jobTitle, index) => addEntry(
          node,
          jobTitle,
          years[index] || '',
          [companies[index], locations[index]].filter(Boolean).join(' · '),
          lines(descriptions[index] || ''),
        ));
        if (node.children.length > 1) fragment.append(node);
      }
      if (key === 'education') {
        const institutions = values(form, 'education_institution');
        const degrees = values(form, 'education_degree');
        const years = values(form, 'education_years');
        const descriptions = values(form, 'education_description');
        const node = section(title);
        institutions.forEach((institution, index) => addEntry(
          node,
          institution,
          years[index] || '',
          degrees[index] || '',
          [],
          descriptions[index] || '',
        ));
        if (node.children.length > 1) fragment.append(node);
      }
      if (key === 'projects') {
        const node = section(title);
        form.querySelectorAll('[name="project_ids"]:checked').forEach((checkbox) => {
          const id = checkbox.value;
          addEntry(
            node,
            value(form, `project_name_${id}`),
            value(form, `project_years_${id}`),
            value(form, `project_role_${id}`),
            lines(value(form, `project_description_${id}`)),
          );
        });
        if (node.children.length > 1) fragment.append(node);
      }
      if (key === 'skills') {
        const skills = lines(value(form, 'skills'));
        if (skills.length) {
          const node = section(title);
          node.append(text('p', skills.join(' / ')));
          fragment.append(node);
        }
      }
      if (key === 'self_evaluation') {
        const bullets = lines(value(form, 'self_evaluation'));
        if (bullets.length) {
          const node = section(title);
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
