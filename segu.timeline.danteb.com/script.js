document.addEventListener('DOMContentLoaded', function () {
    const timelineContainer = document.querySelector('.timeline');
    const timelineItems = document.querySelectorAll('.timeline-item');
    const detailImage = document.getElementById('detail-image');
    const memoDisplay = document.getElementById('memo-display');
    const memoDate = document.getElementById('memo-date');
    const timelineLine = document.querySelector('.timeline-line');

    // Clear any existing markers on the timeline line.
    timelineLine.innerHTML = '';

    // Gather all dates and determine the earliest and latest dates.
    const dates = Array.from(timelineItems).map(item => new Date(item.getAttribute('data-date')));
    const minDate = new Date(Math.min(...dates));
    const maxDate = new Date(Math.max(...dates));

    // Define the end boundary as the start of the year after the last event.
    const startBoundary = new Date(minDate.getFullYear(), 0, 1);
    const endBoundary = new Date(maxDate.getFullYear() + 1, 0, 1);
    const totalTimeSpan = endBoundary - startBoundary;

    // Determine the horizontal and vertical dimensions of the timeline container.
    const containerWidth = timelineContainer.clientWidth;
    const containerHeight = timelineContainer.clientHeight;
    const timelineY = containerHeight / 2; // timeline-line is at vertical center

    // Set a uniform offset (in pixels) so photos don't obscure the marker lines.
    const photoOffset = 30;

    // Position each timeline item based on its date and alternate above and below the timeline.
    Array.from(timelineItems).forEach((item, index) => {
        const date = new Date(item.getAttribute('data-date'));
        const timeDiff = date - startBoundary;
        // Compute left percentage relative to the extended time span.
        const percent = (timeDiff / totalTimeSpan) * 100;
        item.style.left = percent + "%";

        // Alternate vertical positioning with an extra offset:
        if (index % 2 === 0) {
            // Even-indexed items: position above the timeline.
            item.style.top = (timelineY - item.offsetHeight - photoOffset) + "px";
        } else {
            // Odd-indexed items: position below the timeline.
            item.style.top = (timelineY + photoOffset) + "px";
        }

        // Reposition the timeline label relative to the photo.
        const label = item.querySelector('.timeline-label');
        if (label) {
            if (index % 2 === 0) {
                label.classList.add('above');
            } else {
                label.classList.add('below');
            }
        }

        // Create a marker that connects the photo to the timeline line.
        const marker = document.createElement('div');
        marker.className = 'photo-marker';
        // Use the computed percentage and container width to center the marker.
        const centerPx = (percent / 100) * containerWidth;
        marker.style.left = (centerPx - 1) + "px";

        // Marker always spans the gap defined by photoOffset.
        if (index % 2 === 0) {
            // For even-indexed items: marker runs from photo's bottom edge to the timeline.
            marker.style.top = (timelineY - photoOffset) + "px";
            marker.style.height = photoOffset + "px";
        } else {
            // For odd-indexed items: marker runs from the timeline to the photo's top edge.
            marker.style.top = timelineY + "px";
            marker.style.height = photoOffset + "px";
        }

        timelineContainer.appendChild(marker);
    });

    // Create year markers along the timeline.
    // The timeline spans from the first year to (last year + 1).
    const startYear = minDate.getFullYear();
    const endYear = maxDate.getFullYear() + 1;
    for (let year = startYear; year <= endYear; year++) {
        const yearFraction = (year - startYear) / (endYear - startYear);
        const yearPercent = yearFraction * 100;
        const marker = document.createElement('div');
        marker.className = 'year-marker';
        // Set a custom property used by CSS for left offset.
        marker.style.setProperty('--marker-left', `${yearPercent}%`);

        const label = document.createElement('span');
        label.className = 'year-label';
        label.innerText = year;
        marker.appendChild(label);

        timelineLine.appendChild(marker);
    }

    // When a timeline item is clicked, update the detail view.
    timelineItems.forEach(item => {
        item.addEventListener('click', function () {
            // Remove active state from all items and set it on the clicked item.
            timelineItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            const itemImg = item.querySelector('img');

            // Update the detail view's image using the full-resolution image source.
            const fullSrc = itemImg.getAttribute('data-full');
            if (fullSrc) {
                detailImage.src = fullSrc;
                detailImage.alt = itemImg.alt;
            }

            // Update the memo text.
            const memo = item.getAttribute('data-memo');
            if (memo) {
                memoDisplay.innerText = memo;
            }

            // Update and localize the date.
            const date = item.getAttribute('data-date');
            if (date) {
                memoDate.setAttribute('datetime', date);
                const dateObject = new Date(date);
                const localizedDate = dateObject.toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                });
                memoDate.innerText = localizedDate;
            }
        });
    });
});