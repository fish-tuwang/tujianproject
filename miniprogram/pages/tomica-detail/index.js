const { createDetailPage } = require('../../lib/page-factory');
const definition = createDetailPage('tomica');
if (typeof Page === 'function') Page(definition);
module.exports = definition;
