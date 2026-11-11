const { createListPage } = require('../../lib/page-factory');
const definition = createListPage('tomica');
if (typeof Page === 'function') Page(definition);
module.exports = definition;
