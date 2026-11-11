const { createDetailPage } = require('../../lib/page-factory');
const definition = createDetailPage('pokemon');
if (typeof Page === 'function') Page(definition);
module.exports = definition;
