// Script para habilitar o comportamento de arrastar e soltar no quadro Kanban
document.addEventListener('DOMContentLoaded', function () {
    // Lista de status que definem cada coluna do quadro
    const statuses = ['solicitado', 'aprovado', 'em_compra', 'entregue'];
    statuses.forEach(function (status) {
        const column = document.getElementById('column-' + status);
        if (!column) return;
        // Inicializa o Sortable para permitir arrastar entre colunas
        new Sortable(column, {
            group: 'kanban',
            animation: 150,
            onEnd: function (evt) {
                const itemEl = evt.item;
                const pedidoId = itemEl.dataset.id;
                const newStatus = evt.to.dataset.status;
                const newPosition = Array.from(evt.to.children).indexOf(itemEl);
                // Realiza a requisição PATCH para atualizar o status e posição do pedido
                fetch('/api/pedidos-compra/' + pedidoId + '/status', {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        status: newStatus,
                        posicao: newPosition
                    })
                }).then(function (response) {
                    if (!response.ok) {
                        console.error('Erro ao atualizar status do pedido');
                    }
                }).catch(function (error) {
                    console.error('Erro ao enviar requisição:', error);
                });
            }
        });
    });
});